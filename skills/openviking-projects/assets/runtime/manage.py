"""Local project onboarding, service control, durable sync and opt-in scheduling."""
import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import plistlib
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo
from project_registry import SERVICE_ROOT as ROOT, REGISTRY_PATH, load_registry, project_entry
from source_selection import package_name, select_text, validate_limits


def atomic(path,value):
    from uuid import uuid4
    path=Path(path);temporary=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        with temporary.open('x') as out:
            os.chmod(temporary,0o600);json.dump(value,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


@contextmanager
def lock(name):
    with (ROOT/'evidence'/name).open('a+') as stream:
        os.chmod(stream.name,0o600)
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('already_running; wait for the existing process instead of starting another.') from None
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def api(endpoint,body=None,key=None,timeout=15):
    config=json.loads((ROOT/'configs/service.json').read_text())
    if key is None:key=(ROOT/'configs/root.key').read_text().strip()
    data=json.dumps(body).encode() if body is not None else None
    request=Request(config['url']+endpoint,data=data,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with build_opener(NoRedirect).open(request,timeout=timeout) as response:value=json.load(response)
    except HTTPError as exc:raise RuntimeError('Local OpenViking API returned HTTP '+str(exc.code)+'; preserve logs and reconcile before retrying.') from None
    if value.get('status') not in {'ok','ready'}:raise RuntimeError('Local OpenViking API did not confirm success.')
    return value.get('result',value)


def credentials(account):
    configs=ROOT/'identities'/account/'configs';configs.mkdir(parents=True,exist_ok=True,mode=0o700)
    admin=configs/'ovcli.conf';reader=configs/'ovcli-reader.conf'
    service=json.loads((ROOT/'configs/service.json').read_text())
    if not admin.exists():
        if json.dumps(account) in json.dumps(api('/api/v1/admin/accounts')):
            raise ValueError('Identity already exists without its local key. Recover it; do not rotate or recreate blindly.')
        value=api('/api/v1/admin/accounts',{'account_id':account,'admin_user_id':'knowledge-admin'})
        atomic(admin,{'url':service['url'],'api_key':value['user_key'],'actor_peer_id':account})
    config=json.loads(admin.read_text())
    if not reader.exists():
        if '"knowledge-reader"' in json.dumps(api('/api/v1/admin/accounts/'+account+'/users',key=config['api_key'])):
            raise ValueError('Reader creation outcome requires key recovery; no blind retry.')
        value=api('/api/v1/admin/accounts/'+account+'/users',{'user_id':'knowledge-reader','role':'user'},key=config['api_key'])
        atomic(reader,{'url':service['url'],'api_key':value['user_key'],'actor_peer_id':account})
    return configs


def validate_policy(workspace,code,source):
    policy=json.loads(Path(source).expanduser().read_text())
    if not isinstance(policy,dict):raise ValueError('Policy must be a JSON object.')
    sources=policy.get('sources')
    if not isinstance(sources,list) or not sources:raise ValueError('Review an explicit nonempty source whitelist first.')
    seen=set();packages={'00-source-policy.md'}
    blocked={'.git','node_modules','.venv','venv','recordings','blobs','oracle','fixtures','prepared-datasets','deploy-artifacts'}
    for spec in sources:
        if (not isinstance(spec,dict) or not isinstance(spec.get('path'),str)
                or not isinstance(spec.get('role'),str) or not spec['role'].strip()
                or not isinstance(spec.get('selector'),dict)):
            raise ValueError('Each source needs path, role and a selector object.')
        name=spec['path'];relative=Path(name);path=workspace/relative
        if (relative.is_absolute() or '..' in relative.parts or blocked.intersection(relative.parts)
                or path.name in {'keylist.json','.env'} or path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to(workspace) or name in seen):
            raise ValueError('Whitelist contains an unsafe, duplicate or missing project-relative document.')
        seen.add(name)
        mode=spec.get('selector',{}).get('mode')
        if path.suffix.lower()=='.json' and mode!='json_projection':raise ValueError('JSON sources must project explicitly reviewed fields.')
        if path.suffix.lower() not in {'.md','.txt','.json'}:raise ValueError('Index reviewed text/Markdown or projected JSON, not raw payloads.')
        if path.stat().st_size>1024*1024:raise ValueError('A source exceeds 1 MiB; prepare a reviewed maintenance extract first.')
        package=package_name(spec.get('file','src-'+hashlib.sha256(name.encode()).hexdigest()[:16]+'.md'))
        if package in packages:raise ValueError('Duplicate or reserved source package name.')
        packages.add(package)
        text=path.read_text(encoding='utf-8')
        try:select_text(text,spec['selector'])
        except (KeyError,TypeError,IndexError) as exc:
            raise ValueError('Source selector is incomplete or invalid: '+name) from exc
    policy.update(schema_version=1,project=str(workspace),scope='viking://resources/projects/'+code+'/current')
    policy.setdefault('max_changed_files',5)
    if not isinstance(policy['max_changed_files'],int) or not 1<=policy['max_changed_files']<=5:raise ValueError('Incremental changes must remain between 1 and 5 per run.')
    policy.setdefault('budgets',{'find':3000,'directory':3000,'read_default':4000,'read_max':15000})
    policy.setdefault('find_default_limit',3);policy.setdefault('find_max_limit',8)
    validate_limits(policy)
    policy['parser_args']={'split_content':False}
    policy.setdefault('source_policy_text','# Project evidence\n\nSelected local snapshots. Read original sources and dates; summaries do not prove live state or grant action authorization.\n')
    return policy


def register(args):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}',args.code):raise ValueError('Use a project code of 1-48 lowercase letters, digits and hyphens.')
    workspace=Path(args.workspace).expanduser().resolve(strict=True)
    if not workspace.is_dir():raise ValueError('Workspace must be an existing directory.')
    policy=validate_policy(workspace,args.code,args.policy)
    if args.dry_run:return {'status':'review-plan','project_code':args.code,'workspace':str(workspace),'sources':[s['path'] for s in policy['sources']],'identity':args.identity,'model_jobs':0,'scheduled':False}
    with lock('registration.lock'):
        entries=load_registry();root=ROOT/'projects'/args.code
        if args.code in entries or root.exists():raise ValueError('Project/state already exists; inspect it instead of overwriting.')
        if any(workspace==Path(p).resolve() for entry in entries.values() for p in entry['workspace_roots']):raise ValueError('Workspace is already registered.')
        ensure_ready();account='project-'+args.code if args.identity=='isolated' else 'knowledge-shared'
        configs=credentials(account)
        for name in ['configs','evidence','logs','prepared','curated']:(root/name).mkdir(parents=True,exist_ok=True,mode=0o700)
        for name in ['ovcli.conf','ovcli-reader.conf']:(root/'configs'/name).symlink_to(configs/name)
        atomic(root/'configs/pilot-policy.json',policy)
        entries[args.code]={'data_root':str(root),'account':account,'workspace_roots':[str(workspace)],'scope':policy['scope']}
        atomic(REGISTRY_PATH,{'schema_version':1,'projects':entries})
    return {'status':'registered','project_code':args.code,'identity':account,'source_count':len(policy['sources']),'model_jobs':0,'scheduled':False}


def owned(pid):
    try:
        result=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True,timeout=3)
        return 'openviking-server' in result.stdout and str(ROOT/'configs/ov.conf') in result.stdout
    except (OSError,subprocess.TimeoutExpired):return False


def readiness():
    config=json.loads((ROOT/'configs/service.json').read_text())
    try:
        with build_opener(NoRedirect).open(config['url']+'/ready',timeout=3) as response:return json.load(response).get('status')=='ready'
    except (OSError,ValueError):return False


def start(wait=True):
    with lock('service-start.lock'):
        pidfile=ROOT/'server.pid'
        if pidfile.exists() and owned(int(pidfile.read_text())):
            pid=int(pidfile.read_text())
        else:
            service=json.loads((ROOT/'configs/service.json').read_text())
            with socket.socket() as probe:
                if probe.connect_ex((service['host'],service['port']))==0:raise ValueError('Configured port belongs to an existing process; choose a different port or explicitly reuse that deployment.')
            with (ROOT/'logs/server.log').open('ab',buffering=0) as out:
                process=subprocess.Popen([sys.executable,str(ROOT/'scripts/manage.py'),'serve'],stdin=subprocess.DEVNULL,stdout=out,stderr=out,
                    start_new_session=True,cwd=ROOT,env={**os.environ,'OVK_HOME':str(ROOT),'PYTHONUNBUFFERED':'1'})
            pid=process.pid;pidfile.write_text(str(pid));pidfile.chmod(0o600)
        if wait:
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                if readiness():return {'status':'ready','pid':pid}
                time.sleep(1)
            raise RuntimeError('Service did not become ready. Preserve the same process and inspect private logs; do not start duplicates.')
    return {'status':'starting','pid':pid}


def ensure_ready():
    if not readiness():start()


def sync_one(code,dry_run=False):
    entry=project_entry(code);root=Path(entry['data_root'])
    with (root/'evidence/scheduled-sync.lock').open('a+') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'skipped','reason':'already_running'}
        started=datetime.now().astimezone().isoformat();record={'status':'running','started_at':started,'project_code':code}
        if not dry_run:atomic(root/'evidence/scheduled-sync-last.json',record)
        try:
            if not dry_run:ensure_ready()
            command=[sys.executable,str(ROOT/'scripts/import_sources.py')]+(['--dry-run'] if dry_run else [])
            with (root/'logs/scheduled-sync.log').open('a+') as log:
                log.write('\n'+started+'\n');log.flush();position=log.tell()
                result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,cwd=root,timeout=3600,
                    env={**os.environ,'OVK_HOME':str(ROOT),'OVK_PROJECT':code})
                log.seek(position);lines=[line for line in log.read().splitlines() if line.strip()]
            if result.returncode:raise RuntimeError('Sync failed; inspect this project log and journal before any retry.')
            outcome=json.loads(lines[-1])
            if dry_run:return outcome
            if outcome.get('status') not in {'complete','unchanged'}:raise RuntimeError('Sync outcome is not confirmed.')
            record.update(status=outcome['status'],result=outcome)
        except Exception as exc:
            if dry_run:raise
            record.update(status='failed',error_type=type(exc).__name__,error='Sync did not complete; preserve project logs/journal and reconcile.')
        record['finished_at']=datetime.now().astimezone().isoformat();atomic(root/'evidence/scheduled-sync-last.json',record)
        return record


def sync_all(scheduled=False):
    config=json.loads((ROOT/'configs/scheduled-projects.json').read_text());now=datetime.now(ZoneInfo(config.get('timezone','Asia/Shanghai')))
    if scheduled:
        if now.weekday() not in config.get('weekdays',[0,1,2,3,4]) or now.strftime('%H:%M')!=config.get('at','12:30'):return None
    with lock('scheduled-all.lock'):
        stamp=ROOT/'evidence/scheduled-last-date.json'
        if scheduled and stamp.exists() and json.loads(stamp.read_text()).get('date')==now.date().isoformat():return None
        names=config.get('enabled_projects');entries=load_registry()
        if not isinstance(names,list) or len(names)!=len(set(names)) or any(n not in entries for n in names):raise ValueError('Invalid enabled project list; no sync was started.')
        if scheduled:atomic(stamp,{'date':now.date().isoformat(),'status':'attempted'})
        record={'started_at':datetime.now().astimezone().isoformat(),'status':'running','projects':{}}
        path=ROOT/'evidence/scheduled-sync-all-last.json';atomic(path,record)
        for name in names:
            record['projects'][name]=sync_one(name);atomic(path,record)
        states={item['status'] for item in record['projects'].values()}
        record.update(status='failed' if 'failed' in states else 'partial' if 'skipped' in states else 'complete' if 'complete' in states else 'unchanged',finished_at=datetime.now().astimezone().isoformat())
        atomic(path,record);return record


def mcp_config(workspace=None,apply=False,config_path=None):
    # The workspace selects knowledge on each request, never the MCP registration.
    if workspace is not None:
        if not Path(workspace).expanduser().resolve(strict=True).is_dir():
            raise ValueError('workspace must be a directory; MCP registration remains global.')
    target=(Path(config_path).expanduser().absolute() if config_path else
            Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))).expanduser().absolute()/'config.toml')
    snippet='''[mcp_servers.openviking]
command = %s
args = [%s]
enabled = true
required = false
startup_timeout_sec = 20
tool_timeout_sec = 35

[mcp_servers.openviking.env]
OVK_HOME = %s
'''%(json.dumps(sys.executable),json.dumps(str(ROOT/'scripts/unified_mcp.py')),json.dumps(str(ROOT)))
    import tomllib
    old=target.read_text() if target.exists() else ''
    config=tomllib.loads(old)
    servers=config.get('mcp_servers',{})
    if 'openviking_projects' in servers:
        raise ValueError('Legacy openviking_projects registration exists; review migration instead of adding a duplicate global MCP.')
    existing=servers.get('openviking')
    if existing is not None:
        same=(existing.get('command')==sys.executable and
              existing.get('args')==[str(ROOT/'scripts/unified_mcp.py')] and
              existing.get('env',{}).get('OVK_HOME')==str(ROOT) and
              existing.get('enabled',True) is True)
        if not same:
            raise ValueError('Global openviking already uses another configuration. Reuse the existing deployment; it was not overwritten.')
        return {'status':'already_configured','mcp_name':'openviking','registration_scope':'global',
                'config_file':str(target),'applied':False,'changed':False,'restart_required':False,'trust_changed':False}
    if apply:
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            backup=ROOT/'evidence'/('mcp-backup-'+hashlib.sha256(str(target).encode()).hexdigest()[:12]+'-'+str(time.time_ns())+'.toml')
            backup.write_text(old);backup.chmod(0o600)
        # Keep the complete original config if writing or replacement fails.
        fd,temporary=tempfile.mkstemp(prefix='.'+target.name+'.',dir=target.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                stream.write(old.rstrip()+'\n\n'+snippet);stream.flush();os.fsync(stream.fileno())
            current=target.read_text() if target.exists() else ''
            if current!=old:raise ValueError('Codex config changed during registration; inspect it and retry the preview.')
            os.replace(temporary,target)
        finally:Path(temporary).unlink(missing_ok=True)
    return {'status':'configured' if apply else 'preview','mcp_name':'openviking','registration_scope':'global',
            'config_file':str(target),'applied':apply,'changed':apply,'snippet':snippet,'restart_required':True,'trust_changed':False}


def install_job(kind,apply):
    label='local.openviking.projects.'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:8]+'.'+kind
    command=[sys.executable,str(ROOT/'scripts/manage.py')]+(['serve'] if kind=='service' else ['sync-all','--scheduled'])
    if sys.platform=='darwin':
        target=Path.home()/'Library/LaunchAgents'/(label+'.plist')
        definition={'Label':label,'ProgramArguments':command,'EnvironmentVariables':{'OVK_HOME':str(ROOT)},'RunAtLoad':True,
            'StandardOutPath':str(ROOT/'logs'/(kind+'-job.log')),'StandardErrorPath':str(ROOT/'logs'/(kind+'-job-error.log'))}
        if kind=='schedule':definition['StartInterval']=60
        if apply:
            if target.exists():raise ValueError('LaunchAgent already exists; inspect it rather than replacing.')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(plistlib.dumps(definition));target.chmod(0o600)
            subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(target)],check=True,timeout=20)
        return {'job':str(target),'applied':apply,'definition':definition}
    if sys.platform.startswith('linux'):
        unit=Path.home()/'.config/systemd/user'/(label+'.service')
        def quote(value):return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
        body='[Unit]\nDescription=OpenViking project '+kind+'\n\n[Service]\nType='+('simple' if kind=='service' else 'oneshot')+'\nEnvironment='+quote('OVK_HOME='+str(ROOT))+'\nExecStart='+' '.join(quote(x) for x in command)+'\n\n[Install]\nWantedBy=default.target\n'
        timer=unit.with_suffix('.timer');timer_text='[Unit]\nDescription=OpenViking schedule clock\n[Timer]\nOnCalendar=*-*-* *:*:00\nAccuracySec=1s\nUnit='+unit.name+'\n[Install]\nWantedBy=timers.target\n'
        if apply:
            if unit.exists() or (kind=='schedule' and timer.exists()):raise ValueError('Systemd user unit exists; preserve it.')
            unit.parent.mkdir(parents=True,exist_ok=True);unit.write_text(body)
            if kind=='schedule':timer.write_text(timer_text)
            subprocess.run(['systemctl','--user','daemon-reload'],check=True,timeout=20)
            subprocess.run(['systemctl','--user','enable','--now',timer.name if kind=='schedule' else unit.name],check=True,timeout=20)
        return {'job':str(unit),'applied':apply,'unit':body,'timer':timer_text if kind=='schedule' else None}
    raise ValueError('Use macOS LaunchAgent or Linux/WSL2 systemd user service for this runtime.')


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    for name in ['start','serve','stop','status']:sub.add_parser(name)
    p=sub.add_parser('doctor');p.add_argument('--probe-models',action='store_true')
    p=sub.add_parser('project');commands=p.add_subparsers(dest='action',required=True)
    p=commands.add_parser('add');p.add_argument('code');p.add_argument('--workspace',required=True);p.add_argument('--policy',required=True);p.add_argument('--identity',choices=['isolated','shared'],default='isolated');p.add_argument('--dry-run',action='store_true')
    p=commands.add_parser('sync');p.add_argument('code');p.add_argument('--dry-run',action='store_true')
    p=commands.add_parser('alias');p.add_argument('code');p.add_argument('--workspace',required=True)
    p=sub.add_parser('sync-all');p.add_argument('--scheduled',action='store_true')
    p=sub.add_parser('mcp');p.add_argument('--workspace',help='Optional workspace check; registration remains global');p.add_argument('--config-file');p.add_argument('--apply',action='store_true')
    p=sub.add_parser('autostart');p.add_argument('--apply',action='store_true')
    p=sub.add_parser('schedule');p.add_argument('--enable',action='append',default=[]);p.add_argument('--disable',action='append',default=[]);p.add_argument('--at',default='12:30');p.add_argument('--timezone',default='Asia/Shanghai');p.add_argument('--apply',action='store_true')
    p=sub.add_parser('verify');p.add_argument('code');p.add_argument('--query',required=True);p.add_argument('--contains',action='append',default=[])
    args=parser.parse_args()
    if args.command=='serve':
        p=ROOT/'server.pid'
        if p.exists() and int(p.read_text())!=os.getpid() and owned(int(p.read_text())):
            print(json.dumps({'status':'already_running','login_job':'installed for a future login; current process preserved'}))
            return 0
        service=json.loads((ROOT/'configs/service.json').read_text())
        with socket.socket() as probe:
            if probe.connect_ex((service['host'],service['port']))==0:raise ValueError('Port is occupied; no existing PID or service was replaced.')
        p.write_text(str(os.getpid()));p.chmod(0o600)
        from provider_runtime import runtime_environment
        binary=ROOT/'venv/bin/openviking-server'
        os.execve(str(binary),[str(binary),'--config',str(ROOT/'configs/ov.conf'),'--host',service['host'],'--port',str(service['port'])],runtime_environment())
    elif args.command=='doctor':
        if args.probe_models:
            return subprocess.call([sys.executable,str(ROOT/'scripts/probe_models.py')],env={**os.environ,'OVK_HOME':str(ROOT)})
        return subprocess.call([sys.executable,str(ROOT/'scripts/provider_runtime.py'),'doctor'],env={**os.environ,'OVK_HOME':str(ROOT)})
    elif args.command=='start':result=start()
    elif args.command=='stop':
        with lock('service-start.lock'):
            p=ROOT/'server.pid'
            if not p.exists():raise ValueError('No owned server PID was found; no process was signalled.')
            pid=int(p.read_text())
            if not owned(pid):raise ValueError('PID is stale or belongs to another process; no process was signalled.')
            os.kill(pid,signal.SIGTERM);deadline=time.monotonic()+15
            while owned(pid) and time.monotonic()<deadline:time.sleep(0.2)
            if owned(pid):raise RuntimeError('Graceful shutdown is pending; preserve state and wait. No force kill was issued.')
            if p.exists() and int(p.read_text())==pid:p.unlink()
            result={'status':'stopped'}
    elif args.command=='status':result={'ready':readiness(),'projects':list(load_registry()),'service_root':str(ROOT)}
    elif args.command=='project':
        if args.action=='add':result=register(args)
        elif args.action=='sync':result=sync_one(args.code,args.dry_run)
        else:
            with lock('registration.lock'):
                entries=load_registry();project_entry(args.code);alias=Path(args.workspace).expanduser().resolve(strict=True)
                if not alias.is_dir():raise ValueError('Alias must be a workspace directory.')
                from project_registry import resolve_workspace
                try:existing=resolve_workspace(str(alias))
                except ValueError:existing=None
                if existing and existing['project_code']!=args.code:raise ValueError('Alias belongs to another project.')
                if str(alias) not in entries[args.code]['workspace_roots']:entries[args.code]['workspace_roots'].append(str(alias))
                atomic(REGISTRY_PATH,{'schema_version':1,'projects':entries});result={'status':'alias-registered','project_code':args.code,'workspace':str(alias)}
    elif args.command=='sync-all':result=sync_all(args.scheduled)
    elif args.command=='mcp':result=mcp_config(args.workspace,args.apply,args.config_file)
    elif args.command=='autostart':result=install_job('service',args.apply)
    elif args.command=='schedule':
        config=json.loads((ROOT/'configs/scheduled-projects.json').read_text());names=config['enabled_projects'][:]
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',args.at):raise ValueError('Use HH:MM.')
        ZoneInfo(args.timezone)
        for code in args.enable:
            entry=project_entry(code);path=Path(entry['data_root'])/'evidence/mcp-check.json'
            if not path.exists() or not json.loads(path.read_text()).get('passed'):raise ValueError('Verify this project before enabling scheduled model jobs.')
            current=json.loads((Path(entry['data_root'])/'evidence/import-receipt.json').read_text())
            if json.loads(path.read_text()).get('snapshot_id')!=current.get('snapshot_id'):raise ValueError('Verify the current indexed snapshot before enabling scheduled jobs.')
            if code not in names:names.append(code)
        for code in args.disable:
            if code in names:names.remove(code)
        result={'enabled_projects':names,'weekdays':[0,1,2,3,4],'at':args.at,'timezone':args.timezone,'applied':args.apply}
        if args.apply:atomic(ROOT/'configs/scheduled-projects.json',{k:v for k,v in result.items() if k!='applied'})
        result['clock_job']=install_job('schedule',False)
        if args.apply:
            # Existing scheduler jobs need no replacement when the enabled list changes.
            job=Path(result['clock_job']['job'])
            if not job.exists():result['clock_job']=install_job('schedule',True)
    elif args.command=='verify':
        command=[sys.executable,str(ROOT/'scripts/verify_mcp.py'),args.code,'--query',args.query]
        for value in args.contains:command+=['--contains',value]
        return subprocess.call(command,env={**os.environ,'OVK_HOME':str(ROOT)})
    else:raise ValueError('Unknown operation.')
    if result is not None:print(json.dumps(result,ensure_ascii=False,indent=2))
    return int(isinstance(result,dict) and result.get('status') in {'failed','partial'})


if __name__=='__main__':
    os.umask(0o077)
    try:raise SystemExit(main())
    except (ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError) as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__,'message':str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'Local operation failed; inspect private evidence and logs before retrying.'},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(1)

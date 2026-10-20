#!/usr/bin/env python3
"""Portable bootstrap. Keep mutable state and credentials outside the skill."""
import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path
from urllib.parse import urlsplit

VERSION = '0.5.0'
SKILL = Path(__file__).resolve().parents[1]
INDEXES = {'pypi':'https://pypi.org/simple', 'tuna':'https://pypi.tuna.tsinghua.edu.cn/simple',
           'aliyun':'https://mirrors.aliyun.com/pypi/simple/'}
REQUIREMENTS = [f'openviking=={VERSION}', 'mcp>=1.27,<2', 'tiktoken>=0.9,<1']


def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,temporary=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            json.dump(value,out,ensure_ascii=False,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
        os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def state_root(value):
    if any(ord(char)<32 for char in str(value)):raise ValueError('State directory cannot contain control characters.')
    root=Path(value).expanduser().resolve()
    if root==Path.home() or root==Path('/') or root.is_relative_to(SKILL):
        raise ValueError('Choose a dedicated state directory outside the skill, not a home/filesystem root.')
    return root


def checked_url(value, local_http=False):
    p=urlsplit(value)
    if p.username or p.password or p.query or p.fragment or not p.hostname:
        raise ValueError('URLs must not contain credentials, query strings or fragments.')
    if p.scheme!='https' and not (local_http and p.scheme=='http' and p.hostname in {'localhost','127.0.0.1','::1'}):
        raise ValueError('Use HTTPS; HTTP is permitted only for local model services.')
    return value.rstrip('/')


def interpreter(root):
    return root/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


def install_plan(root,index='auto',wheelhouse=None,python=None):
    py=str(interpreter(root));common=[py,'-m','pip','install','--disable-pip-version-check','--no-input',
        '--timeout','15','--retries','0','--prefer-binary','--only-binary=:all:']
    if wheelhouse:
        source=Path(wheelhouse).expanduser().resolve(strict=True)
        if not source.is_dir():raise ValueError('wheelhouse must be a directory.')
        commands=[common+['--no-index','--find-links',str(source),*REQUIREMENTS]]
    else:
        urls=list(INDEXES.values()) if index=='auto' else [INDEXES.get(index,index)]
        commands=[common+['--index-url',checked_url(url),*REQUIREMENTS] for url in urls]
    return {'version':VERSION,'state_root':str(root),'python':python or sys.executable,
            'venv':str(root/'venv'),'commands':commands,'source_build':False,'github_required':False}


def initialize(root):
    root.mkdir(parents=True,exist_ok=True,mode=0o700);root.chmod(0o700)
    marker=root/'.ovk-state.json'
    if not marker.exists():write_json(marker,{'owner':'openviking-projects','schema_version':1})
    for name in ['configs','scripts','logs','evidence','projects','identities','cache/tiktoken']:
        (root/name).mkdir(parents=True,exist_ok=True,mode=0o700)
    for name,value in [('projects.json',{'schema_version':1,'projects':{}}),('scheduled-projects.json',{'enabled_projects':[]})]:
        p=root/'configs'/name
        if not p.exists():write_json(p,value)


def runtime_plan(root):
    """Check compatibility before dependencies or existing state can be changed."""
    sources=sorted((SKILL/'assets/runtime').glob('*.py'))
    if not sources:raise ValueError('Skill runtime assets are missing.')
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    old=root/'configs/runtime-manifest.json'
    if old.exists() and json.loads(old.read_text())!=manifest:
        raise ValueError('Installed runtime differs. Back up and review an explicit upgrade; existing state was preserved.')
    for source in sources:
        target=root/'scripts'/source.name
        if target.exists() and target.read_bytes()!=source.read_bytes():
            raise ValueError('Installed runtime was locally changed; refusing to overwrite it.')
    return sources,manifest


def deploy_runtime(root):
    sources,manifest=runtime_plan(root)
    for source in sources:
        target=root/'scripts'/source.name
        if not target.exists():shutil.copyfile(source,target);target.chmod(0o600)
    write_json(root/'configs/runtime-manifest.json',manifest)


def install(root,args):
    plan=install_plan(root,args.index,args.wheelhouse,args.python)
    if args.dry_run:return plan
    if os.name=='nt':raise ValueError('The bundled locking/runtime targets macOS/Linux; run it inside WSL2 on Windows.')
    if sys.version_info<(3,11):raise ValueError('This skill runtime needs Python 3.11+; OpenViking itself supports older Python.')
    if root.exists() and any(root.iterdir()) and not (root/'configs/runtime-manifest.json').exists() and not (root/'.ovk-state.json').exists():
        raise ValueError('State directory is nonempty and is not owned by this runtime; choose a new directory or reuse its original manager.')
    runtime_plan(root)
    initialize(root)
    if not interpreter(root).exists():
        if args.python and Path(args.python).resolve()!=Path(sys.executable).resolve():
            subprocess.run([args.python,'-m','venv',str(root/'venv')],check=True,timeout=90)
        else:venv.EnvBuilder(with_pip=True).create(root/'venv')
    target_version=json.loads(subprocess.check_output([str(interpreter(root)),'-c','import sys,json;print(json.dumps(list(sys.version_info[:2])))'],text=True,timeout=15))
    if target_version<[3,11]:raise ValueError('The chosen runtime Python must be 3.11 or later.')
    attempts=[]
    for number,command in enumerate(plan['commands'],1):
        log=root/'logs'/f'install-{int(time.time())}-{number}.log'
        try:
            with log.open('w',encoding='utf-8') as out:
                # Sources and installation location belong to this venv plan.
                # Keep explicit enterprise certificates, but not inherited pip behavior.
                pip_env={k:v for k,v in os.environ.items() if not k.startswith('PIP_') or k in {'PIP_CERT','PIP_CLIENT_CERT'}}
                pip_env['PIP_CONFIG_FILE']=os.devnull
                result=subprocess.run(command,stdout=out,stderr=subprocess.STDOUT,timeout=1200,env=pip_env)
            attempts.append({'source':command[command.index('--index-url')+1] if '--index-url' in command else 'offline-wheelhouse',
                             'exit_code':result.returncode,'log':str(log)})
            if result.returncode==0:break
        except subprocess.TimeoutExpired:
            attempts.append({'source':'timed-out','exit_code':124,'log':str(log)})
    if not attempts or attempts[-1]['exit_code']:
        write_json(root/'evidence/install-last.json',{'status':'failed','attempts':attempts})
        raise RuntimeError('Package installation failed. Inspect private install logs, wheel/platform compatibility and mirror availability; no source build was attempted.')
    result=subprocess.run([str(interpreter(root)),'-c',
        'import importlib.metadata,json; print(json.dumps({n:importlib.metadata.version(n) for n in ["openviking","mcp","tiktoken"]}))'],capture_output=True,text=True,check=True,timeout=20)
    versions=json.loads(result.stdout)
    if versions['openviking']!=VERSION:raise RuntimeError('Installed OpenViking version does not match the supported runtime.')
    deploy_runtime(root)
    evidence={'status':'installed','versions':versions,'platform':platform.platform(),'attempts':attempts,
              'state_root':str(root),'github_required':False,'configured':False}
    write_json(root/'evidence/install-last.json',evidence)
    return evidence


def configure(root,args):
    if not (root/'configs/runtime-manifest.json').exists():raise ValueError('Install the runtime first.')
    paths=[root/'configs'/name for name in ['ov.conf','service.json','root.key']]
    if any(p.exists() for p in paths):raise ValueError('Configuration already exists; preserve it and review changes instead of reinitializing.')
    models=json.loads(Path(args.models).expanduser().read_text())
    keys=json.loads(Path(args.secrets).expanduser().read_text()) if args.secrets else {}
    if not isinstance(keys,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in keys.items()):raise ValueError('Secrets file must be a JSON string mapping.')
    required=set();compiled={}
    for name in ['embedding','vlm']:
        spec=models[name]
        if 'api_key' in spec:raise ValueError('Use a named api_key_env and a local credential source, not inline model keys.')
        if not isinstance(spec.get('model'),str) or not spec['model'].strip():raise ValueError('Confirm both model names before configuring.')
        if spec.get('provider') not in {'openai','ollama','volcengine','azure'}:
            raise ValueError('Use a supported API-compatible provider; OAuth and other providers require an explicit adapter.')
        item={'provider':spec['provider'],'model':spec['model'],'api_base':checked_url(spec['api_base'],local_http=True)}
        variable=spec.get('api_key_env')
        if variable:
            if not re.fullmatch(r'[A-Z][A-Z0-9_]{2,80}',variable) or variable in {'HOME','PATH','USER','TMPDIR','PYTHONPATH','PYTHONHOME','OVK_HOME','OVK_PROJECT','OVK_ROOT_KEY','OPENVIKING_CONFIG_FILE','OPENVIKING_CLI_CONFIG_FILE','TIKTOKEN_CACHE_DIR','LD_PRELOAD','DYLD_INSERT_LIBRARIES'}:raise ValueError('Invalid dedicated model credential variable.')
            value=keys.get(variable) or os.environ.get(variable)
            if not value:raise ValueError('A required model credential is absent; provide it locally, not in chat.')
            keys[variable]=value;required.add(variable);item['api_key']='${'+variable+'}'
        elif spec['provider']!='ollama':raise ValueError('An explicit api_key_env is required for this provider.')
        options=spec.get('options',{})
        allowed={'dimension','input','encoding_format','batch_size'} if name=='embedding' else {'max_tokens','max_concurrent','max_retries','timeout','reasoning_effort','api_version'}
        if set(options)-allowed:raise ValueError('Unknown model options; review the provider adapter before extending it.')
        if name=='embedding' and 'dimension' not in options:raise ValueError('Confirm the embedding dimension before configuring this index; do not guess it.')
        if name=='embedding' and 'dimension' in options and (type(options['dimension']) is not int or options['dimension']<=0):raise ValueError('Embedding dimension must be a positive integer.')
        item.update(options);compiled[name]=item
    if not 1024<=args.port<=65535:raise ValueError('Choose an unprivileged local TCP port.')
    key=secrets.token_urlsafe(36)
    config={'storage':{'workspace':str(root/'data'),'agfs':{'backend':'local'},'vectordb':{'backend':'local'}},
        'server':{'host':'127.0.0.1','port':args.port,'auth_mode':'api_key','root_api_key':'${OVK_ROOT_KEY}',
                  'cors_origins':[f'http://127.0.0.1:{args.port}'],'usage_reporter':{'enabled':False}},
        'embedding':{'dense':compiled['embedding']},'vlm':compiled['vlm']}
    write_json(root/'configs/provider-keys.json',{k:keys[k] for k in required})
    p=root/'configs/root.key';p.write_text(key+'\n');p.chmod(0o600)
    write_json(root/'configs/ov.conf',config)
    write_json(root/'configs/service.json',{'url':f'http://127.0.0.1:{args.port}','host':'127.0.0.1','port':args.port,'version':VERSION})
    return {'status':'configured','url':f'http://127.0.0.1:{args.port}','authentication':'api_key','credentials_printed':False,'model_access_verified':False}


def fetch_source(root,args):
    checked_url(args.url)
    if not re.fullmatch(r'[0-9a-f]{40}',args.commit):raise ValueError('Pin a full verified upstream commit, not a branch or moving tag.')
    target=Path(args.destination).expanduser().resolve()
    if target.exists():raise ValueError('Source destination exists; refusing to replace it.')
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ovk-source-',dir=target.parent) as temp:
        checkout=Path(temp)/'checkout'
        for command in [['git','init',str(checkout)],['git','-C',str(checkout),'remote','add','origin',args.url],
                        ['git','-C',str(checkout),'fetch','--depth=1','origin',args.commit],
                        ['git','-C',str(checkout),'checkout','--detach','FETCH_HEAD']]:
            result=subprocess.run(command,capture_output=True,text=True,timeout=180)
            if result.returncode:raise RuntimeError('Pinned source fetch failed; no build or install was attempted.')
        actual=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],timeout=10).decode().strip()
        if actual!=args.commit:raise ValueError('Mirror returned a different commit.')
        shutil.move(str(checkout),str(target))
    return {'status':'source-fetched','commit':actual,'path':str(target),'built':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',dest='state_home',default=os.environ.get('OVK_HOME',str(Path.home()/'.openviking-projects')))
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('preflight')
    p=sub.add_parser('install');p.add_argument('--index',default='auto');p.add_argument('--wheelhouse');p.add_argument('--python');p.add_argument('--dry-run',action='store_true')
    p=sub.add_parser('configure');p.add_argument('--models',required=True);p.add_argument('--secrets');p.add_argument('--port',type=int,default=1933)
    p=sub.add_parser('fetch-source');p.add_argument('--url',required=True);p.add_argument('--commit',required=True);p.add_argument('--destination',required=True)
    # Runtime command grammar is owned by the deployed manager.
    for name in ['doctor','start','stop','status','project','sync-all','mcp','autostart','schedule','verify']:
        sub.add_parser(name,add_help=False)
    args,rest=parser.parse_known_args()
    if rest and args.command in {'preflight','install','configure','fetch-source'}:
        parser.error('unrecognized arguments: '+' '.join(rest))
    root=state_root(args.state_home)
    if args.command=='preflight':
        result={'python':sys.version.split()[0],'platform':platform.platform(),'architecture':platform.machine(),
            'native_runtime_supported':os.name!='nt' and sys.version_info>=(3,11),'state_root':str(root),
            'existing_runtime':(root/'configs/runtime-manifest.json').exists(),'git_available':bool(shutil.which('git')),
            'notes':'Windows: run the bundled project runtime in WSL2. Python wheels must match the OS/CPU baseline.'}
    elif args.command=='install':result=install(root,args)
    elif args.command=='configure':result=configure(root,args)
    elif args.command=='fetch-source':result=fetch_source(root,args)
    else:
        command=[str(interpreter(root)),str(root/'scripts/manage.py'),args.command,*rest]
        if not interpreter(root).is_file() or not (root/'scripts/manage.py').is_file():raise ValueError('Install this portable runtime first.')
        return subprocess.call(command,env={**os.environ,'OVK_HOME':str(root)})
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,KeyError,OSError,RuntimeError,subprocess.SubprocessError) as exc:
        # Config/credential values and third-party HTTP responses are never echoed.
        print(json.dumps({'status':'failed','error_type':type(exc).__name__,'message':str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'Local operation failed; inspect the operation-specific private evidence.'},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(1)

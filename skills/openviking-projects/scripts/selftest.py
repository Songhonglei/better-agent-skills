#!/usr/bin/env python3
"""Offline invariants and optional native integration using local fake models."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import ModuleType,SimpleNamespace
from unittest.mock import patch

SKILL=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ovk_bootstrap',SKILL/'scripts/ovk.py')
bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
runtime=SKILL/'assets/runtime'
with patch.object(sys,'path',[str(runtime),*sys.path]):
    spec=importlib.util.spec_from_file_location('ovk_manage',runtime/'manage.py')
    manager=importlib.util.module_from_spec(spec);spec.loader.exec_module(manager)


class Offline(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory(prefix='ovk-unit-');self.root=Path(self.tmp.name)/'state'
    def tearDown(self):self.tmp.cleanup()
    def test_mirror_order_and_no_github_or_tls_bypass(self):
        plan=bootstrap.install_plan(self.root)
        self.assertEqual([c[c.index('--index-url')+1] for c in plan['commands']],[url.rstrip('/') for url in bootstrap.INDEXES.values()])
        self.assertFalse(plan['github_required']);self.assertFalse(self.root.exists())
        for command in plan['commands']:
            self.assertNotIn('--trusted-host',command);self.assertNotIn('--extra-index-url',command)
    def test_offline_never_sets_online_index(self):
        wheelhouse=Path(self.tmp.name)/'wheels';wheelhouse.mkdir()
        commands=bootstrap.install_plan(self.root,wheelhouse=wheelhouse)['commands']
        self.assertEqual(len(commands),1);self.assertIn('--no-index',commands[0]);self.assertNotIn('--index-url',commands[0])
    def test_failed_package_source_falls_back_without_global_pip_config(self):
        bootstrap.initialize(self.root)
        py=self.root/'venv/bin/python';py.parent.mkdir(parents=True);py.write_text('fixture')
        seen=[]
        def execute(command,**kwargs):
            if '-m' in command and 'pip' in command:
                seen.append(command[command.index('--index-url')+1])
                self.assertEqual(kwargs['env']['PIP_CONFIG_FILE'],os.devnull)
                for key in ['PIP_EXTRA_INDEX_URL','PIP_TARGET','PIP_PREFIX','PIP_USER','PIP_NO_INDEX','PIP_FIND_LINKS']:
                    self.assertNotIn(key,kwargs['env'])
                self.assertEqual(kwargs['env']['PIP_CERT'],'fixture-ca.pem')
                return SimpleNamespace(returncode=1 if len(seen)==1 else 0)
            return SimpleNamespace(returncode=0,stdout=json.dumps({'openviking':'0.5.0','mcp':'1.27.0','tiktoken':'0.9.0'}))
        args=SimpleNamespace(index='auto',wheelhouse=None,python=None,dry_run=False)
        pip_variables={'PIP_EXTRA_INDEX_URL':'https://extra.example.org/simple','PIP_TARGET':'outside-venv','PIP_PREFIX':'outside-prefix','PIP_USER':'1','PIP_NO_INDEX':'1','PIP_FIND_LINKS':'unselected-wheels','PIP_CERT':'fixture-ca.pem'}
        with patch.object(bootstrap.subprocess,'run',side_effect=execute),patch.object(bootstrap.subprocess,'check_output',return_value='[3, 13]'),patch.dict(os.environ,pip_variables),patch.object(bootstrap.platform,'platform',return_value='fixture-platform'):
            result=bootstrap.install(self.root,args)
        self.assertEqual(seen,['https://pypi.org/simple','https://pypi.tuna.tsinghua.edu.cn/simple'])
        self.assertEqual(result['status'],'installed')
    def test_credentials_and_untrusted_url_rejected(self):
        for url in ['http://untrusted.example.org/simple','https://user:secret@example.org/simple','https://example.org/simple?token=x']:
            with self.assertRaises(ValueError):bootstrap.checked_url(url)
        self.assertTrue(bootstrap.checked_url('http://127.0.0.1:8888',local_http=True))
    def test_runtime_update_preserves_local_changes(self):
        bootstrap.initialize(self.root);bootstrap.deploy_runtime(self.root)
        target=self.root/'scripts/router_worker.py';target.write_text('local change\n')
        with self.assertRaises(ValueError):bootstrap.deploy_runtime(self.root)
        self.assertEqual(target.read_text(),'local change\n')
        args=SimpleNamespace(index='auto',wheelhouse=None,python=None,dry_run=False)
        before={str(path.relative_to(self.root)):path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        with patch.object(bootstrap.subprocess,'run') as run,patch.object(bootstrap.subprocess,'check_output') as check,patch.object(bootstrap.venv.EnvBuilder,'create') as create:
            with self.assertRaises(ValueError):bootstrap.install(self.root,args)
            run.assert_not_called();check.assert_not_called();create.assert_not_called()
        self.assertEqual(before,{str(path.relative_to(self.root)):path.read_bytes() for path in self.root.rglob('*') if path.is_file()})
    def test_configuration_private_refs_and_no_overwrite(self):
        bootstrap.initialize(self.root);bootstrap.deploy_runtime(self.root)
        models=Path(self.tmp.name)/'models.json';keys=Path(self.tmp.name)/'keys.json'
        model={'provider':'openai','api_base':'https://gateway.example.org/v1','model':'test-model','api_key_env':'OVK_TEST_KEY'}
        models.write_text(json.dumps({'embedding':{**model,'options':{'dimension':16}},'vlm':model}));keys.write_text(json.dumps({'OVK_TEST_KEY':'unit-test-only-value'}))
        args=SimpleNamespace(models=str(models),secrets=str(keys),port=19441)
        result=bootstrap.configure(self.root,args)
        self.assertEqual(result['authentication'],'api_key')
        self.assertNotIn('unit-test-only-value',(self.root/'configs/ov.conf').read_text())
        self.assertEqual((self.root/'configs/provider-keys.json').stat().st_mode&0o777,0o600)
        original=(self.root/'configs/root.key').read_bytes()
        with self.assertRaises(ValueError):bootstrap.configure(self.root,args)
        self.assertEqual((self.root/'configs/root.key').read_bytes(),original)
    def test_unknown_dimension_does_not_create_configuration(self):
        bootstrap.initialize(self.root);bootstrap.deploy_runtime(self.root)
        models=Path(self.tmp.name)/'models.json';keys=Path(self.tmp.name)/'keys.json'
        model={'provider':'openai','api_base':'https://gateway.example.org/v1','model':'test-model','api_key_env':'OVK_TEST_KEY'}
        models.write_text(json.dumps({'embedding':model,'vlm':model}));keys.write_text(json.dumps({'OVK_TEST_KEY':'unit-test-only-value'}))
        with self.assertRaises(ValueError):bootstrap.configure(self.root,SimpleNamespace(models=str(models),secrets=str(keys),port=19441))
        self.assertFalse((self.root/'configs/ov.conf').exists())
    def test_mirror_requires_full_commit_before_git(self):
        args=SimpleNamespace(url='https://mirror.example.org/project.git',commit='main',destination=str(Path(self.tmp.name)/'source'))
        with patch.object(bootstrap.subprocess,'run') as run:
            with self.assertRaises(ValueError):bootstrap.fetch_source(self.root,args)
            run.assert_not_called()
    def test_state_must_live_outside_skill(self):
        for root in [str(SKILL/'state'),str(Path.home()),'/']:
            with self.assertRaises(ValueError):bootstrap.state_root(root)
    def test_unknown_nonempty_state_is_preserved(self):
        self.root.mkdir();important=self.root/'existing-config';important.write_text('keep')
        args=SimpleNamespace(index='tuna',wheelhouse=None,python=None,dry_run=False)
        with self.assertRaises(ValueError):bootstrap.install(self.root,args)
        self.assertEqual(important.read_text(),'keep')
    def test_mcp_global_preview_and_single_registration_for_two_workspaces(self):
        import tomllib
        bootstrap.initialize(self.root)
        codex=Path(self.tmp.name)/'codex';codex.mkdir()
        config=codex/'config.toml';original='model = "fixture-model"\n\n[mcp_servers.other]\ncommand = "other-tool"\n'
        config.write_text(original)
        workspaces=[Path(self.tmp.name)/code for code in ['alpha','beta']]
        for workspace in workspaces:workspace.mkdir()
        with patch.object(manager,'ROOT',self.root),patch.dict(os.environ,{'CODEX_HOME':str(codex)}):
            preview=manager.mcp_config(workspace=str(workspaces[0]))
            self.assertEqual(preview['status'],'preview');self.assertEqual(config.read_text(),original)
            self.assertEqual(preview['config_file'],str(config));self.assertEqual(preview['mcp_name'],'openviking')
            outcome=manager.mcp_config(workspace=str(workspaces[0]),apply=True)
            self.assertEqual(outcome['registration_scope'],'global')
            saved=config.read_bytes()
            repeated=manager.mcp_config(workspace=str(workspaces[1]),apply=True)
        self.assertEqual(repeated['status'],'already_configured');self.assertFalse(repeated['changed'])
        self.assertEqual(config.read_bytes(),saved)
        tables=tomllib.loads(config.read_text())
        self.assertEqual(set(tables['mcp_servers']),{'openviking','other'})
        self.assertEqual(tables['model'],'fixture-model')
        self.assertEqual(tables['mcp_servers']['openviking']['env']['OVK_HOME'],str(self.root))
        backups=list((self.root/'evidence').glob('mcp-backup-*.toml'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_text(),original)
        self.assertEqual(config.stat().st_mode&0o777,0o600)
        for workspace in workspaces:self.assertFalse((workspace/'.codex').exists())
    def test_mcp_existing_deployment_and_legacy_registration_are_preserved(self):
        bootstrap.initialize(self.root)
        target=Path(self.tmp.name)/'config.toml'
        for name in ['openviking','openviking_projects']:
            original='[mcp_servers.'+name+']\ncommand = "existing-deployment"\n'
            target.write_text(original)
            with patch.object(manager,'ROOT',self.root):
                with self.assertRaises(ValueError):manager.mcp_config(apply=True,config_path=str(target))
            self.assertEqual(target.read_text(),original)
        self.assertEqual(list((self.root/'evidence').glob('mcp-backup-*.toml')),[])
    def test_mcp_without_workspace_defaults_to_codex_home(self):
        config_home=Path(self.tmp.name)/'codex'
        command=[sys.executable,str(runtime/'manage.py'),'mcp']
        result=subprocess.run(command,env={**os.environ,'OVK_HOME':str(self.root),'CODEX_HOME':str(config_home)},capture_output=True,text=True,check=True,timeout=10)
        preview=json.loads(result.stdout)
        self.assertEqual(preview['config_file'],str(config_home/'config.toml'))
        self.assertEqual(preview['mcp_name'],'openviking');self.assertFalse(config_home.exists())
    def test_bootstrap_rejects_unknown_flags_without_mutation(self):
        for operation in [('preflight','--typo-ignored'),('install','--dry-run','--indx','tuna')]:
            with self.subTest(operation=operation):
                command=[sys.executable,str(SKILL/'scripts/ovk.py'),'--home',str(self.root),*operation]
                result=subprocess.run(command,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,2);self.assertFalse(self.root.exists())
    def test_plain_folder_snapshot_without_git_or_with_git_timeout(self):
        workspace=Path(self.tmp.name).resolve()/'project';workspace.mkdir();(workspace/'README.md').write_text('# Demo\n\nCurrent documentation.\n')
        profile=ModuleType('project_profile');profile.ROOT=self.root;profile.SERVICE_ROOT=self.root;profile.PROJECT_ID='demo';profile.SCOPE='viking://resources/projects/demo/current'
        policy={'project':str(workspace),'scope':profile.SCOPE,'sources':[{'path':'README.md','file':'README.md','role':'current-status','selector':{'mode':'full'}}]}
        with patch.dict(sys.modules,{'project_profile':profile}),patch.object(sys,'path',[str(runtime),*sys.path]):
            spec=importlib.util.spec_from_file_location('ovk_prepare',runtime/'prepare_sources.py')
            prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)
            for failure in [FileNotFoundError('Git unavailable'),subprocess.TimeoutExpired('git',3)]:
                with self.subTest(failure=type(failure).__name__),patch.object(prepare.subprocess,'run',side_effect=failure):
                    manifest,files,snapshots=prepare.build_snapshot(self.root,policy,scan_key='unused-test-key')
                    self.assertIsNone(manifest['git_head']);self.assertIsNone(manifest['sources'][0]['repository'])
                    self.assertEqual(files['README.md'].decode(),'# Demo\n\nCurrent documentation.\n')
                    self.assertTrue(snapshots);self.assertFalse(self.root.exists())
    def test_invalid_policy_is_rejected_before_account_or_state_creation(self):
        workspace=Path(self.tmp.name).resolve()/'project';workspace.mkdir();(workspace/'README.md').write_text('# Demo\n\nCurrent documentation.\n')
        valid={'path':'README.md','role':'current-status','selector':{'mode':'full'}}
        policies=[{'sources':[{**valid,'role':''}]},{'sources':[{**valid,'selector':{'mode':'typo'}}]},
                  {'sources':[{**valid,'selector':{'mode':'sections','titles':['Missing']}}]},
                  {'sources':[{**valid,'file':'00-source-policy.md'}]},
                  {'sources':[valid],'budgets':{'find':3000,'directory':3000,'read_default':4000,'read_max':32000}},
                  {'sources':[valid],'max_changed_files':True}]
        policy=Path(self.tmp.name)/'policy.json'
        for value in policies:
            policy.write_text(json.dumps(value))
            args=SimpleNamespace(code='demo',workspace=str(workspace),policy=str(policy),identity='isolated',dry_run=False)
            with self.subTest(policy=value),patch.object(manager,'ROOT',self.root),patch.object(manager,'ensure_ready') as ready,patch.object(manager,'credentials') as credentials:
                with self.assertRaises(ValueError):manager.register(args)
                ready.assert_not_called();credentials.assert_not_called();self.assertFalse(self.root.exists())
    def test_section_selection_ignores_nested_or_different_code_fences(self):
        document='# Status\n\nKnown facts.\n\n````markdown\n```python\n# Example\n```\n````\n\n~~~text\n```\n# Another example\n~~~\n\n# Current\n\nCurrent facts.\n'
        selected,_=manager.select_text(document,{'mode':'sections','titles':['Status']})
        self.assertIn('# Example',selected);self.assertNotIn('# Current',selected)
        for title in ['Example','Another example']:
            with self.subTest(title=title),self.assertRaises(ValueError):manager.select_text(document,{'mode':'sections','titles':[title]})
    def test_mcp_atomic_write_failure_preserves_original(self):
        bootstrap.initialize(self.root);target=Path(self.tmp.name)/'config.toml';original='model = "existing"\n';target.write_text(original)
        with patch.object(manager,'ROOT',self.root),patch.object(manager.os,'replace',side_effect=OSError('fixture replacement failure')):
            with self.assertRaises(OSError):manager.mcp_config(apply=True,config_path=str(target))
        self.assertEqual(target.read_text(),original);self.assertEqual(list(target.parent.glob('.config.toml.*')),[])
    def test_mcp_concurrent_edit_is_preserved(self):
        bootstrap.initialize(self.root);target=Path(self.tmp.name)/'config.toml';target.write_text('model = "existing"\n')
        newer='model = "newer-external-edit"\n'
        with patch.object(manager,'ROOT',self.root),patch.object(manager.os,'fsync',side_effect=lambda _:target.write_text(newer)):
            with self.assertRaisesRegex(ValueError,'changed during registration'):manager.mcp_config(apply=True,config_path=str(target))
        self.assertEqual(target.read_text(),newer);self.assertEqual(list(target.parent.glob('.config.toml.*')),[])


class Models(BaseHTTPRequestHandler):
    calls={'embedding':0,'vlm':0}
    def log_message(self,*args):pass
    def do_POST(self):
        try:
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            if self.path.endswith('/embeddings'):
                type(self).calls['embedding']+=1;items=body.get('input',[])
                if not isinstance(items,list) or (items and isinstance(items[0],int)):items=[items]
                # Constant vectors test transport and storage, never semantic quality.
                result={'object':'list','model':body['model'],'data':[{'object':'embedding','index':i,'embedding':[1.0]+[0.0]*15} for i,_ in enumerate(items)],'usage':{'prompt_tokens':1,'total_tokens':1}}
            elif self.path.endswith('/chat/completions'):
                type(self).calls['vlm']+=1
                content='# Project knowledge\n\nLocal fixture documentation, current status and verified project boundaries.\n\n## Navigation\nRead project source files for the current marker.\n'
                result={'id':'local-test','object':'chat.completion','created':int(time.time()),'model':body['model'],
                        'choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':'stop'}],
                        'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
            else:self.send_error(404);return
            data=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        except Exception:self.send_error(500)


def native(native_python):
    import venv
    work=Path(tempfile.mkdtemp(prefix='ovk-native-'));root=work/'state';server=None;success=False
    commands=[]
    def run(*arguments,timeout=180,expected=0):
        command=[str(root/'venv/bin/python'),str(SKILL/'scripts/ovk.py'),'--home',str(root),*arguments]
        result=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
        commands.append({'args':list(arguments),'exit_code':result.returncode})
        with (work/'commands.log').open('a') as out:out.write(json.dumps(list(arguments))+'\n'+result.stdout+result.stderr+'\n')
        if result.returncode!=expected:raise RuntimeError('Native step failed: '+str(arguments)+'; preserve '+str(work))
        if expected:return None
        try:return json.loads(result.stdout)
        except ValueError:return result.stdout
    try:
        version=subprocess.check_output([native_python,'-c','import importlib.metadata; print(importlib.metadata.version("openviking"))'],text=True,timeout=15).strip()
        if version!=bootstrap.VERSION:raise ValueError('Native fixture requires the supported OpenViking version.')
        site=subprocess.check_output([native_python,'-c','import sysconfig; print(sysconfig.get_paths()["purelib"])'],text=True,timeout=15).strip()
        subprocess.run([native_python,'-m','venv','--without-pip',str(root/'venv')],check=True,timeout=45)
        fixture_site=subprocess.check_output([str(root/'venv/bin/python'),'-c','import sysconfig; print(sysconfig.get_paths()["purelib"])'],text=True,timeout=15).strip()
        Path(fixture_site,'existing-runtime.pth').write_text(site+'\n')
        for name in ['ov','openviking-server']:
            source=Path(native_python).parent/name
            (root/'venv/bin'/name).symlink_to(source)
        bootstrap.initialize(root);bootstrap.deploy_runtime(root)
        # Public tokenizer cache only; never read configs or credentials from the old installation.
        url='https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken';cache_name=hashlib.sha1(url.encode()).hexdigest()
        # A caller may supply the public cache explicitly, avoiding any assumed installation location.
        cache=os.environ.get('OVK_TEST_TOKENIZER_CACHE', '')
        if cache and (Path(cache)/cache_name).exists():shutil.copyfile(Path(cache)/cache_name,root/'cache/tiktoken'/cache_name)
        else:
            env={**os.environ,'TIKTOKEN_CACHE_DIR':str(root/'cache/tiktoken')}
            subprocess.run([native_python,'-c','import tiktoken;tiktoken.get_encoding("o200k_base")'],env=env,check=True,timeout=45)
        server=ThreadingHTTPServer(('127.0.0.1',0),Models);threading.Thread(target=server.serve_forever,daemon=True).start()
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        model={'provider':'openai','api_base':f'http://127.0.0.1:{server.server_port}/v1','model':'local-fake-model','api_key_env':'OVK_FIXTURE_KEY'}
        embedding={**model,'options':{'dimension':16,'encoding_format':'float','batch_size':8}}
        vlm={**model,'options':{'max_tokens':128,'max_concurrent':2,'max_retries':0,'timeout':10}}
        models=work/'models.json';models.write_text(json.dumps({'embedding':embedding,'vlm':vlm}))
        key=work/'keys.json';key.write_text(json.dumps({'OVK_FIXTURE_KEY':'local-test-key-with-no-external-access'}))
        run('configure','--models',str(models),'--secrets',str(key),'--port',str(port))
        run('doctor','--probe-models');run('start',timeout=150)
        projects=[]
        for code in ['alpha','beta','gamma']:
            workspace=work/code;workspace.mkdir();(workspace/'README.md').write_text('# '+code+'\n\nCurrent marker '+code+'-one.\n')
            policy=work/(code+'-policy.json');policy.write_text(json.dumps({'sources':[{'path':'README.md','file':'01-README.md','role':'current-status','selector':{'mode':'full'}}]}))
            run('project','add',code,'--workspace',str(workspace),'--policy',str(policy),'--dry-run')
            run('project','add',code,'--workspace',str(workspace),'--policy',str(policy))
            plan=run('project','sync',code,'--dry-run');assert plan['model_calls']==0
            outcome=run('project','sync',code,timeout=240);assert outcome['status']=='complete'
            run('verify',code,'--query','Current marker for '+code,'--contains',code+'-one',timeout=240)
            projects.append(code)
        workspace=work/'alpha';target=workspace/'README.md';target.write_text(target.read_text()+'\nA meaningful maintenance update.\n')
        assert run('project','sync','alpha',timeout=180)['status']=='complete'
        run('verify','alpha','--query','Current marker for alpha','--contains','alpha-one',timeout=240)
        before=dict(Models.calls)
        for code in projects:assert run('project','sync',code)['status']=='unchanged'
        assert Models.calls==before,'Unchanged sync called a model.'
        # Generate configs and jobs, but never apply a login/scheduler job during tests.
        config_file=work/'codex/config.toml'
        run('mcp','--config-file',str(config_file),'--apply')
        assert run('mcp','--workspace',str(work/'beta'),'--config-file',str(config_file),'--apply')['status']=='already_configured'
        run('autostart');run('schedule','--enable','alpha')
        # Verify every native directed account pair with an existing source URI.
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from urllib.parse import urlencode
        registry=json.loads((root/'configs/projects.json').read_text())['projects']
        assert len({entry['account'] for entry in registry.values()})==3
        denials=[]
        for code,entry in registry.items():
            config=json.loads((Path(entry['data_root'])/'configs/ovcli-reader.conf').read_text())
            for other,foreign in registry.items():
                if other==code:continue
                uri=foreign['scope']+'/01-README/01-README.md'
                request=Request(config['url']+'/api/v1/content/read?'+urlencode({'uri':uri}),headers={'Authorization':'Bearer '+config['api_key']})
                try:urlopen(request,timeout=5).close()
                except HTTPError as exc:assert exc.code in {403,404}
                else:raise AssertionError('Native account isolation failed.')
                denials.append(code+' -> '+other)
        result={'passed':True,'projects':projects,'native_version':version,'model_calls':dict(Models.calls),
            'real_provider_calls':0,'three_isolated_accounts':True,'native_directed_account_denials':denials,'single_file_update':True,'unchanged_zero_model_calls':True,
            'system_jobs_applied':False,'full_package_download_tested':False,'native_dependency_source':'existing explicitly provided venv','commands':commands}
        success=True;return result
    except Exception as exc:
        return {'passed':False,'error_type':type(exc).__name__,'message':str(exc),'failure_workspace':str(work),'commands':commands}
    finally:
        if (root/'server.pid').exists():
            try:run('stop',timeout=20)
            except Exception:pass
        if server:server.shutdown();server.server_close()
        if success:
            for attempt in range(3):
                try:shutil.rmtree(work);break
                except OSError:
                    if attempt==2:print('Native test passed; temporary files retained for cleanup: '+str(work),file=sys.stderr)
                    else:time.sleep(1)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--native-python');parser.add_argument('--report');args=parser.parse_args()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Offline);result=unittest.TextTestRunner(stream=sys.stderr,verbosity=2).run(suite)
    report={'offline':{'passed':result.wasSuccessful(),'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors)}}
    if args.native_python and result.wasSuccessful():report['native']=native(str(Path(args.native_python).expanduser().absolute()))
    report['passed']=all(value.get('passed',False) for value in report.values() if isinstance(value,dict))
    if args.report:
        path=Path(args.report).expanduser();path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2));return int(not report['passed'])


if __name__=='__main__':raise SystemExit(main())

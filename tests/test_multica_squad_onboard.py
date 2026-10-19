import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

SKILL = Path(__file__).resolve().parents[1] / 'skills' / 'multica-squad-onboard'
spec = importlib.util.spec_from_file_location('onboard_under_test', SKILL / 'scripts/onboard.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def uid(n):
    return str(UUID(int=n))


P, W, S, L, A, K, R = [uid(n) for n in range(1, 8)]
CTX = {'profile': None, 'server_url': 'https://multica.example', 'workspace_id': W}


class FakeCLI:
    def __init__(self):
        self.context = dict(CTX)
        self.writes = []
        self.fail_after_add = False
        self.project = {'id': P, 'workspace_id': W, 'lead_type': 'agent', 'lead_id': L,
                        'description': '项目原业务说明'}
        self.squad = {'id': S, 'workspace_id': W, 'leader_id': L, 'instructions': '小队原业务规则'}
        self.squads = [self.squad]
        self.members = [{'member_type': 'agent', 'member_id': L},
                        {'member_type': 'agent', 'member_id': A}]
        self.runtime = {'id': R, 'status': 'online'}
        self.agents = {x: {'id': x, 'workspace_id': W, 'name': '成员',
                          'runtime_id': R, 'runtime_bound': True, 'max_concurrent_tasks': 2,
                          'status': 'working', 'instructions': '保留业务职责',
                          'runtime_config': {'secret': 'never-export-this'},
                          'skills': [{'id': uid(22), 'enabled': True}, {'id': uid(23), 'enabled': False}]}
                       for x in [L, A]}
        self.skill = {'id': K, 'workspace_id': W, 'skill_name': m.PUBLIC_SKILL,
                      'content': '---\nname: multica-squad-load-balancer\nversion: "1.0.3"\n---\n正文',
                      'files': [{'path': 'scripts/squad_balance.py', 'content': 'print("preview")'},
                                {'path': 'references/contract.md', 'content': 'contract'}]}

    def get(self, kind, identity):
        items = {'project': {P: self.project}, 'squad': {S: self.squad},
                 'agent': self.agents, 'skill': {K: self.skill}}
        return copy.deepcopy(items[kind][identity])

    def run(self, args, **_kwargs):
        if args == ['squad', 'list']:
            return copy.deepcopy(self.squads)
        if args == ['squad', 'member', 'list', S]:
            return copy.deepcopy(self.members)
        if args == ['runtime', 'list']:
            return [copy.deepcopy(self.runtime)]
        self.writes.append(list(args))
        if args[:3] == ['agent', 'skills', 'add']:
            target = self.agents[args[3]]
            target['skills'].append({'id': args[5], 'enabled': True})
            if self.fail_after_add:
                self.fail_after_add = False
                raise m.OnboardError('模拟远端成功但响应超时')
            return {}
        kind, action, identity, flag, value = args
        assert action == 'update' and flag in ['--description', '--instructions', '--lead']
        obj = self.project if kind == 'project' else self.squad if kind == 'squad' else self.agents[identity]
        if flag == '--lead':
            obj['lead_type'] = 'agent'; obj['lead_id'] = value
            if getattr(self, 'fail_after_set_lead', False):
                self.fail_after_set_lead = False
                raise m.OnboardError('远端设置成功但响应超时')
        else:
            obj[flag[2:]] = value
        return copy.deepcopy(obj)


def plan_for(cli):
    snapshot = m.inspect(cli, P, S)
    assert not snapshot['blockers']
    return m.prepare(cli, snapshot, copy.deepcopy(snapshot), K)


def save_plan(tmp_path, cli):
    path = tmp_path / 'plan.json'
    m.write_private(path, plan_for(cli))
    return path


def test_missing_project_lead_reports_user_setup_and_never_writes():
    cli = FakeCLI()
    cli.project['lead_type'] = 'user'
    result = m.inspect(cli, P)
    assert result['blockers'] and '项目设置' in result['blockers'][0]
    assert cli.writes == []


def test_explicit_squad_does_not_bypass_multiple_squads():
    cli = FakeCLI()
    cli.squads.append({**cli.squad, 'id': uid(9)})
    assert m.inspect(cli, P, S)['blockers']
    assert cli.writes == []


def test_mismatching_user_squad_is_blocked_not_reassigned():
    cli = FakeCLI()
    assert m.inspect(cli, P, uid(9))['blockers']
    assert cli.project['lead_id'] == L and cli.squad['leader_id'] == L


@pytest.mark.parametrize('change', ['missing_leader', 'no_worker', 'duplicate_worker'])
def test_invalid_member_relationships_are_blocked(change):
    cli = FakeCLI()
    if change == 'missing_leader': cli.members = cli.members[1:]
    if change == 'no_worker': cli.members = cli.members[:1]
    if change == 'duplicate_worker': cli.members.append(cli.members[1])
    assert m.inspect(cli, P)['blockers']
    assert cli.writes == []


def test_runtime_requires_user_repair_without_changing_capacity():
    cli = FakeCLI()
    cli.runtime['status'] = 'offline'
    result = m.inspect(cli, P)
    assert result['blockers']
    assert cli.agents[A]['max_concurrent_tasks'] == 2 and cli.writes == []


def test_business_roles_and_skills_not_required_and_secrets_not_exported():
    cli = FakeCLI()
    cli.agents[A]['skills'] = []
    result = m.inspect(cli, P)
    assert not result['blockers']
    assert 'never-export-this' not in json.dumps(result)
    assert 'runtime_config' not in json.dumps(result)


@pytest.mark.parametrize('value', [{'items': [], 'has_more': True}, {'items': [], 'next_cursor': 'x'},
                                  {'items': [], 'total': 1}])
def test_truncated_lists_fail_closed(value):
    with pytest.raises(m.OnboardError): m.records(value, 'members')


def test_scoped_merge_is_idempotent_and_preserves_other_project():
    other = m.merge('业务原文\n', '其他项目约束', uid(100))
    first = m.merge(other, '新项目约束', P)
    assert m.merge(first, '新项目约束', P) == first
    assert other in first
    updated = m.merge(first, '新版约束', P)
    assert other in updated and '新项目约束' not in updated


@pytest.mark.parametrize('text', [f'<!-- multica-squad-onboard:{P}:begin -->',
                                f'<!-- multica-squad-onboard:{P}:end --><!-- multica-squad-onboard:{P}:begin -->'])
def test_broken_markers_are_not_overwritten(text):
    with pytest.raises(m.OnboardError): m.merge(text, 'body', P)


def test_prepare_rejects_stale_reviewed_snapshot():
    cli = FakeCLI()
    snapshot = m.inspect(cli, P, S)
    cli.agents[A]['instructions'] = '其他人修改了原文'
    with pytest.raises(m.OnboardError): m.prepare(cli, m.inspect(cli, P, S), snapshot, K)


def test_incomplete_public_package_is_rejected():
    cli = FakeCLI()
    cli.skill['files'] = []
    with pytest.raises(m.OnboardError): plan_for(cli)


def test_no_production_assignment_or_role_changes_and_idempotent_apply(tmp_path, monkeypatch):
    cli = FakeCLI()
    monkeypatch.setattr(m, 'CLI', lambda ctx: cli)
    path = save_plan(tmp_path, cli)
    first = m.apply(path)
    assert first['status'] == 'configured'
    assert cli.project['lead_id'] == L and cli.squad['leader_id'] == L
    assert cli.members == FakeCLI().members
    assert all({uid(22), K} == set(m.enabled_ids(a)) for a in cli.agents.values())
    assert all(any(s['id'] == uid(23) and s['enabled'] is False for s in a['skills']) for a in cli.agents.values())
    assert len(cli.writes) == 6  # 2 additive assignments, project/squad/2 agent text fields.
    original_writes = len(cli.writes)
    assert m.apply(path)['status'] == 'configured'
    assert len(cli.writes) == original_writes
    assert all('issue' not in command and 'dispatch' not in command for command in cli.writes)
    journal = json.loads(Path(first['journal']).read_text())
    assert journal['status'] == 'completed' and all(op['status'] == 'verified' for op in journal['operations'])


def test_tampered_plan_cannot_write_arbitrary_text(tmp_path, monkeypatch):
    cli = FakeCLI()
    monkeypatch.setattr(m, 'CLI', lambda ctx: cli)
    plan = plan_for(cli)
    plan['targets'][0]['after'] = '覆盖整个项目'
    plan['plan_id'] = m.digest({k: v for k, v in plan.items() if k != 'plan_id'})
    path = tmp_path / 'tampered.json'
    m.write_private(path, plan)
    with pytest.raises(m.OnboardError): m.apply(path)
    assert cli.writes == []


def test_concurrent_original_instruction_change_is_preserved(tmp_path, monkeypatch):
    cli = FakeCLI()
    monkeypatch.setattr(m, 'CLI', lambda ctx: cli)
    path = save_plan(tmp_path, cli)
    cli.agents[A]['instructions'] = '另一操作者的业务修改'
    with pytest.raises(m.OnboardError): m.apply(path)
    assert cli.writes == [] and cli.agents[A]['instructions'] == '另一操作者的业务修改'


def test_uncertain_add_requires_reconcile_and_does_not_repeat_side_effect(tmp_path, monkeypatch):
    cli = FakeCLI()
    monkeypatch.setattr(m, 'CLI', lambda ctx: cli)
    path = save_plan(tmp_path, cli)
    cli.fail_after_add = True
    with pytest.raises(m.OnboardError): m.apply(path)
    assert len(cli.writes) == 1
    with pytest.raises(m.OnboardError): m.apply(path)
    assert len(cli.writes) == 1
    assert m.apply(path, resume=True)['status'] == 'configured'
    adds = [c for c in cli.writes if c[:3] == ['agent', 'skills', 'add']]
    assert len(adds) == 2


def test_private_paths_modes_and_exclusive_create(tmp_path):
    path = tmp_path / 'state.json'
    m.write_private(path, {'ok': True})
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError): m.write_private(path, {'ok': False})
    with pytest.raises(m.OnboardError): m.outside(SKILL / 'unsafe.json')
    link = tmp_path / 'link'
    link.symlink_to(SKILL, target_is_directory=True)
    with pytest.raises(m.OnboardError): m.outside(link / 'unsafe.json')


@pytest.mark.parametrize('value', [f'https://user:secret@multica.example/ws/projects/{P}',
                                 f'http://multica.example/ws/projects/{P}',
                                 f'https://multica.example/ws/issues/{P}', '--debug'])
def test_project_locator_rejects_unsafe_or_wrong_input(value):
    with pytest.raises(m.OnboardError): m.locator(value, 'projects')


def test_cli_error_does_not_expose_stderr_or_runtime_secrets(monkeypatch):
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr='Cookie=secret'))
    with pytest.raises(m.OnboardError) as caught: m.CLI(CTX).run(['project', 'get', P])
    assert 'secret' not in str(caught.value)


def test_squad_url_anchors_environment_when_project_is_only_uuid(monkeypatch):
    seen = []
    class ContextCLI:
        def __init__(self, context):
            self.context = dict(context)
            seen.append(dict(context))
        def run(self, args, **kwargs):
            assert args == ['workspace', 'list']
            return [{'id': W, 'slug': 'workspace'}]
        def get(self, kind, identity):
            return {'id': P, 'workspace_id': W}
    monkeypatch.setattr(m, 'CLI', ContextCLI)
    cli, project, squad = m.context_for(SimpleNamespace(project=P, squad_id=f'https://chosen.example/workspace/squads/{S}',
                                                       profile=None, server_url=None, workspace_id=None))
    assert cli.context['server_url'] == 'https://chosen.example'
    assert project == P and squad == S and all(c['server_url'] == 'https://chosen.example' for c in seen)


@pytest.mark.parametrize('boundary_order', [('other-begin', 'own-begin', 'other-end', 'own-end'),
                                           ('other-begin', 'own-begin', 'own-end', 'other-end')])
def test_cross_project_overlapping_blocks_are_rejected(boundary_order):
    marker = lambda kind: f'<!-- multica-squad-onboard:{uid(200) if kind.startswith("other") else P}:{kind.split("-")[1]} -->'
    text = '\n'.join(marker(kind) for kind in boundary_order)
    with pytest.raises(m.OnboardError): m.merge(text, 'replacement', P)


@pytest.mark.parametrize('mode', ['remove_disabled', 'enable_disabled'])
def test_changes_to_disabled_business_assignments_stop_apply(tmp_path, monkeypatch, mode):
    cli = FakeCLI()
    monkeypatch.setattr(m, 'CLI', lambda ctx: cli)
    path = save_plan(tmp_path, cli)
    if mode == 'remove_disabled': cli.agents[A]['skills'] = cli.agents[A]['skills'][:1]
    else: cli.agents[A]['skills'][1]['enabled'] = True
    with pytest.raises(m.OnboardError): m.apply(path)
    assert cli.writes == []


@pytest.mark.parametrize('mode', ['missing_version', 'duplicate_file'])
def test_unverifiable_public_package_is_rejected(mode):
    cli = FakeCLI()
    if mode == 'missing_version': cli.skill['content'] = '---\nname: multica-squad-load-balancer\n---\n正文'
    else: cli.skill['files'].append(cli.skill['files'][0])
    with pytest.raises(m.OnboardError): plan_for(cli)


def test_public_source_reference_does_not_echo_url_credentials_or_query():
    cli = FakeCLI()
    cli.skill['config'] = {'origin': 'registry', 'source_url': 'https://user:password@hub.example/skill?token=secret', 'version': '1.0.3'}
    result = m.skill_identity(cli, K)
    output = json.dumps(result)
    assert result['origin']['source_host'] == 'hub.example'
    assert 'password' not in output and 'secret' not in output and 'token=' not in output


def test_corrupt_state_has_safe_public_cli_error(tmp_path):
    import subprocess
    path = tmp_path / 'corrupt.json'
    path.write_text('{"private-secret":')
    result = subprocess.run(['python3', str(SKILL/'scripts/onboard.py'), 'apply', '--plan-file', str(path)],
                            capture_output=True,text=True,timeout=10)
    assert result.returncode == 2
    assert json.loads(result.stdout)['status'] == 'blocked'
    assert 'private-secret' not in result.stdout and 'Traceback' not in result.stderr


@pytest.mark.parametrize('text', ['<!-- multica-squad-onboard:not-a-uuid:begin -->',
                                '<!-- multica-squad-onboard:00000000-0000-0000-0000-00000000000A:begin -->'])
def test_unknown_or_noncanonical_managed_markers_stop_without_rewriting(text):
    with pytest.raises(m.OnboardError): m.merge(text, 'body', P)


def nested_source_config(cli):
    import hashlib
    return {'origin':{'type':'registry','slug':m.PUBLIC_SKILL,'source_url':'https://hub.example/detail','version':'1.0.2'},
            'local_patch':{'version':'1.0.3','base_version':'1.0.2','reason':'allow working',
                           'script_sha256':hashlib.sha256(cli.skill['files'][0]['content'].encode()).hexdigest()}}


def test_nested_provenance_records_official_base_and_local_patch_separately():
    cli=FakeCLI();cli.skill['config']=nested_source_config(cli)
    identity=m.skill_identity(cli,K)
    assert identity['origin']['kind']=='registry'
    assert identity['origin']['base_version']=='1.0.2'
    assert identity['origin']['local_patch_version']=='1.0.3'
    assert identity['origin']['source_host']=='hub.example'
    before=identity['origin']['metadata_hash']
    cli.skill['config']['local_patch']['reason']='reviewed change'
    assert m.skill_identity(cli,K)['origin']['metadata_hash']!=before


@pytest.mark.parametrize('field,value',[('version','1.0.4'),('script_sha256','0'*64)])
def test_inconsistent_local_patch_proof_is_rejected(field,value):
    cli=FakeCLI();cli.skill['config']=nested_source_config(cli)
    cli.skill['config']['local_patch'][field]=value
    with pytest.raises(m.OnboardError):m.skill_identity(cli,K)


def test_project_lead_repair_requires_explicit_authorization(tmp_path):
    cli=FakeCLI();cli.project['lead_type']=None;cli.project['lead_id']=None
    with pytest.raises(m.OnboardError):m.set_project_lead(cli,P,S,L,tmp_path/'repair.json')
    assert cli.writes==[] and not (tmp_path/'repair.json').exists()


def test_authorized_project_lead_repair_changes_only_requested_field_and_is_idempotent(tmp_path):
    cli=FakeCLI();cli.project['lead_type']=None;cli.project['lead_id']=None
    original_members=copy.deepcopy(cli.members);original_squad=copy.deepcopy(cli.squad)
    result=m.set_project_lead(cli,P,S,L,tmp_path/'repair.json',authorized=True)
    assert result['changed'] and cli.project['lead_type']=='agent' and cli.project['lead_id']==L
    assert cli.project['description']=='项目原业务说明' and cli.members==original_members and cli.squad==original_squad
    assert cli.writes==[['project','update',P,'--lead',L]]
    assert not m.set_project_lead(cli,P,S,L,tmp_path/'repair.json',authorized=True)['changed']
    assert len(cli.writes)==1


@pytest.mark.parametrize('kind',['wrong_agent','multiple_squads','missing_worker'])
def test_project_lead_repair_rejects_invalid_target(tmp_path,kind):
    cli=FakeCLI();target=L
    if kind=='wrong_agent':target=A
    if kind=='multiple_squads':cli.squads.append({**cli.squad,'id':uid(33)})
    if kind=='missing_worker':cli.members=cli.members[:1]
    with pytest.raises(m.OnboardError):m.set_project_lead(cli,P,S,target,tmp_path/'repair.json',authorized=True)
    assert cli.writes==[]


def test_project_lead_repair_uncertain_result_reconciles_without_duplicate_write(tmp_path):
    cli=FakeCLI();cli.project['lead_type']=None;cli.project['lead_id']=None
    cli.fail_after_set_lead=True
    with pytest.raises(m.OnboardError):m.set_project_lead(cli,P,S,L,tmp_path/'repair.json',authorized=True)
    assert len(cli.writes)==1
    assert json.loads((tmp_path/'repair.json').read_text())['status']=='uncertain'
    assert not m.set_project_lead(cli,P,S,L,tmp_path/'repair.json',authorized=True)['changed']
    assert len(cli.writes)==1


def test_project_lead_repair_does_not_override_concurrent_change(tmp_path):
    cli=FakeCLI();cli.project['lead_type']=None;cli.project['lead_id']=None
    original_get=cli.get;count=0
    def get(kind,identity):
        nonlocal count
        if kind=='project':
            count+=1
            if count==2:cli.project['lead_type']='agent';cli.project['lead_id']=uid(1000)
        return original_get(kind,identity)
    cli.get=get
    with pytest.raises(m.OnboardError):m.set_project_lead(cli,P,S,L,tmp_path/'repair.json',authorized=True)
    assert cli.writes==[] and cli.project['lead_id']==uid(1000)


def test_portable_public_package_body_version():
    cli = FakeCLI()
    cli.skill['content'] = ('---\nname: multica-squad-load-balancer\n'
                            'description: >\n  Public scheduler.\n---\n\n'
                            '# Multica scheduler\n\n- **Version**: 1.0.0\n')
    assert m.skill_identity(cli, K)['version'] == '1.0.0'


def test_portable_public_package_requires_parseable_version():
    cli = FakeCLI()
    cli.skill['content'] = ('---\nname: multica-squad-load-balancer\n'
                            'description: >\n  Public scheduler.\n---\nNo version')
    with pytest.raises(m.OnboardError):
        m.skill_identity(cli, K)


def test_frontmatter_version_remains_supported():
    cli = FakeCLI()
    assert m.skill_identity(cli, K)['version'] == '1.0.3'


def test_actual_public_scheduler_package_is_readable():
    cli = FakeCLI()
    scheduler = SKILL.parent / 'multica-squad-load-balancer'
    cli.skill['content'] = (scheduler / 'SKILL.md').read_text()
    cli.skill['files'] = [{'path': path, 'content': (scheduler / path).read_text()}
                         for path in ['scripts/squad_balance.py', 'references/contract.md']]
    assert m.skill_identity(cli, K)['version'] == '1.0.0'

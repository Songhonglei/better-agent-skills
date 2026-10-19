#!/usr/bin/env python3
"""Read existing Multica relationships and apply scoped onboarding metadata only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SKILL = 'multica-squad-load-balancer'
SCHEMA = 'multica-squad-onboard/v1'


class OnboardError(Exception):
    """An actionable, credential-free error suitable for the command output."""


def require(condition, message):
    if not condition:
        raise OnboardError(message)


def uid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise OnboardError('缺少合法 UUID；请提供项目或小队的 ID/URL') from None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def outside(value):
    path = Path(value).expanduser().resolve()
    require(path != ROOT and ROOT not in path.parents, '快照、计划和日志必须位于 Skill 安装目录之外')
    return path


def write_private(path, value, *, replace=False):
    path = outside(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if not replace:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            stream.write(encoded)
    else:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            try:
                os.chmod(temp, 0o600)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                temp.unlink(missing_ok=True)
                raise
        try:
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def read_private(value):
    path = outside(value)
    try:
        with path.open() as stream:
            result = json.load(stream)
    except (OSError, ValueError, UnicodeError):
        raise OnboardError('私有状态文件无法读取或 JSON 损坏；检查原文件并先对账，不删除记录盲重试') from None
    require(isinstance(result, dict), '私有状态文件必须为 JSON 对象')
    return result


def records(value, key):
    if isinstance(value, dict):
        require(not value.get('has_more') and not value.get('next_cursor'), '返回列表被截断，停止配置')
        items = value.get(key, value.get('items'))
        require(not isinstance(value.get('total'), int) or
                (isinstance(items, list) and value['total'] <= len(items)), '返回分页未完整读取，停止配置')
        value = items
    require(isinstance(value, list) and all(isinstance(x, dict) for x in value), '列表响应格式无法核验')
    return value


def endpoint(value):
    parsed = urlsplit(value)
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment and parsed.path in ('', '/'),
            '服务器地址须为不含凭据的 HTTPS origin')
    return value.rstrip('/')


def locator(value, kind):
    if '://' not in value:
        return uid(value), None, None
    parsed = urlsplit(value)
    origin = endpoint(f'{parsed.scheme}://{parsed.netloc}')
    pieces = parsed.path.strip('/').split('/')
    require(len(pieces) == 3 and pieces[1] == kind, f'URL 应为 /<工作区>/{kind}/<UUID>')
    require(not parsed.username and not parsed.password, 'URL 不能包含凭据')
    return uid(pieces[2]), origin, pieces[0]


class CLI:
    def __init__(self, context):
        self.context = dict(context)

    def run(self, args, *, json_output=True):
        command = ['multica']
        for key in ('profile', 'server_url', 'workspace_id'):
            if self.context.get(key):
                command += ['--' + key.replace('_', '-'), self.context[key]]
        command += list(args) + (['--output', 'json'] if json_output else [])
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        except FileNotFoundError:
            raise OnboardError('未安装 multica CLI；请先安装并登录目标环境') from None
        except subprocess.TimeoutExpired:
            raise OnboardError('CLI 超时；若已开始写入，先读取日志和平台对账，不能直接重试') from None
        require(result.returncode == 0, f'Multica {args[0]} {args[1]} 失败；核对登录、环境和权限。写入失败先对账')
        if not json_output:
            return result.stdout
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise OnboardError('CLI 未返回有效 JSON；写入后先对账') from None

    def get(self, kind, identity):
        identity = uid(identity)
        raw = self.run([kind, 'get', identity])
        item = raw.get(kind, raw) if isinstance(raw, dict) else None
        require(isinstance(item, dict) and item.get('id') == identity, f'{kind} 身份不匹配')
        return item


def context_for(args):
    project_id, origin, slug = locator(args.project, 'projects')
    squad_id = None
    if args.squad_id:
        squad_id, squad_origin, squad_slug = locator(args.squad_id, 'squads')
        require(not squad_origin or not origin or squad_origin == origin, '项目与指定小队来自不同服务器')
        require(not squad_slug or not slug or squad_slug == slug, '项目与指定小队来自不同工作区')
        origin = origin or squad_origin
        slug = slug or squad_slug
    require(not origin or not args.server_url or endpoint(args.server_url) == origin,
            'URL 与指定服务器不一致；请先确认环境，不能猜测域名映射')
    context = {'profile': args.profile, 'server_url': origin or args.server_url,
               'workspace_id': args.workspace_id}
    if not context['server_url']:
        raw = CLI(context).run(['config', 'show'], json_output=False)
        match = re.search(r'^\s*server_url\s*:\s*(\S+)\s*$', raw, re.M)
        require(match, '无法识别当前 CLI 服务器；请显式提供已确认的 --server-url')
        context['server_url'] = endpoint(match[1])
    context['server_url'] = endpoint(context['server_url'])
    if context['workspace_id']:
        context['workspace_id'] = uid(context['workspace_id'])
    workspaces = records(CLI(context).run(['workspace', 'list']), 'workspaces')
    if slug:
        found = [w for w in workspaces if w.get('slug') == slug]
        require(len(found) == 1, 'URL 工作区不可见或不唯一；请登录正确环境')
        workspace_id = uid(found[0].get('id'))
        require(not context['workspace_id'] or context['workspace_id'] == workspace_id, '指定工作区与 URL 不一致')
        context['workspace_id'] = workspace_id
    project = CLI(context).get('project', project_id)
    workspace_id = uid(project.get('workspace_id'))
    require(not context['workspace_id'] or context['workspace_id'] == workspace_id, '项目不属于指定工作区')
    require(any(w.get('id') == workspace_id for w in workspaces), '当前身份不可见项目工作区')
    context['workspace_id'] = workspace_id
    return CLI(context), project_id, squad_id


def text_field(item, key):
    value = item.get(key)
    require(value is None or isinstance(value, str), f'{key} 不是可核验的文本')
    return value or ''


def assignments(agent):
    skills = records(agent.get('skills', []), 'skills')
    result = [{'id': uid(s.get('id')), 'enabled': s.get('enabled') is True} for s in skills]
    require(len({s['id'] for s in result}) == len(result), 'Agent Skill 分配重复，停止配置')
    return sorted(result, key=lambda s: s['id'])


def enabled_ids(agent):
    return [s['id'] for s in assignments(agent) if s['enabled']]


def inspect(cli, project_id, squad_id=None):
    project = cli.get('project', project_id)
    require(project.get('workspace_id') == cli.context['workspace_id'], '项目工作区发生变化')
    result = {'schema': SCHEMA, 'context': cli.context, 'project_id': project_id,
              'squad_constraint': squad_id, 'blockers': [], 'warnings': [], 'agents': [],
              'project': {'id': project_id, 'description': text_field(project, 'description')},
              'runtime_verification': '未实测远端 CLI、Python、fcntl、落盘及私有目录；平台在线不代表全部就绪'}
    def block(message):
        result['blockers'].append(message)
    if project.get('archived_at'):
        block('项目已归档；请在 Multica 项目设置中处理后重查')
    if project.get('lead_type') != 'agent' or not project.get('lead_id'):
        block('项目负责人须为 Agent：在项目设置中选择已配置测试/目标小队的队长 Agent')
        return result
    leader_id = uid(project['lead_id'])
    squads = records(cli.run(['squad', 'list']), 'squads')
    found = [s for s in squads if s.get('leader_id') == leader_id
             and s.get('workspace_id') == cli.context['workspace_id'] and not s.get('archived_at')]
    if len(found) != 1:
        block('负责人须在同工作区领导唯一未归档小队：请在 Multica 小队设置修正零匹配或多匹配')
        return result
    actual_squad_id = uid(found[0]['id'])
    if squad_id and actual_squad_id != squad_id:
        block('自动解析的小队不等于用户指定目标；请用户核对项目负责人和小队关系，不能自动换队')
        return result
    squad = cli.get('squad', actual_squad_id)
    require(squad.get('leader_id') == leader_id and squad.get('workspace_id') == cli.context['workspace_id']
            and not squad.get('archived_at'), '小队关系发生变化；重新检查')
    members = records(cli.run(['squad', 'member', 'list', actual_squad_id]), 'members')
    agents = [m for m in members if m.get('member_type') == 'agent']
    ids = [uid(m.get('member_id')) for m in agents]
    if len(set(ids)) != len(ids) or leader_id not in ids or len(set(ids) - {leader_id}) < 1:
        block('请在小队设置中加入队长及至少一名不重复的非队长 Agent 成员')
        return result
    runtime_rows = records(cli.run(['runtime', 'list']), 'runtimes')
    runtimes = {uid(r.get('id')): r for r in runtime_rows}
    result['route'] = {'project_id': project_id, 'workspace_id': cli.context['workspace_id'],
                       'leader_id': leader_id, 'squad_id': actual_squad_id, 'member_ids': sorted(ids)}
    result['squad'] = {'id': actual_squad_id, 'instructions': text_field(squad, 'instructions')}
    for identity in sorted(ids):
        agent = cli.get('agent', identity)
        require(agent.get('workspace_id') == cli.context['workspace_id'], 'Agent 工作区不匹配')
        runtime = runtimes.get(agent.get('runtime_id'), {})
        runtime_online = runtime.get('status') in ('online', 'active', 'ready') and not runtime.get('archived_at')
        problems = []
        if agent.get('archived_at'):
            problems.append('Agent 已归档')
        if not runtime_online or agent.get('runtime_bound') is False:
            problems.append('Runtime 离线或未绑定，请在 Agent/Runtime 设置修复')
        if type(agent.get('max_concurrent_tasks')) is not int or agent['max_concurrent_tasks'] <= 0:
            problems.append('并发上限无效，请在 Agent 设置修复；接入不会自动提高')
        if problems:
            block(f'Agent {identity}：' + '；'.join(problems))
        result['agents'].append({'id': identity, 'name': agent.get('name', identity),
                                 'instructions': text_field(agent, 'instructions'),
                                 'enabled_skill_ids': enabled_ids(agent), 'skill_assignments': assignments(agent),
                                 'status': agent.get('status'),
                                 'runtime_id': agent.get('runtime_id'), 'runtime_status': runtime.get('status'),
                                 'capacity': agent.get('max_concurrent_tasks'),
                                 'role': next((m.get('role') for m in agents if m.get('member_id') == identity), None)})
    return result


def stable(snapshot):
    return {k: snapshot.get(k) for k in ('context', 'project_id', 'squad_constraint', 'route', 'project', 'squad')} | {
        'agents': [{k: a[k] for k in ('id', 'instructions', 'enabled_skill_ids', 'skill_assignments', 'runtime_id', 'capacity', 'role')}
                   for a in snapshot['agents']]}


def summary(snapshot):
    return {k: v for k, v in snapshot.items() if k not in ('project', 'squad', 'agents')} | {
        'agents': [{k: v for k, v in a.items() if k != 'instructions'} for a in snapshot['agents']]}


def skill_identity(cli, identity):
    skill = cli.get('skill', identity)
    require(skill.get('workspace_id') == cli.context['workspace_id'], '公共 Skill 不属于当前工作区')
    require((skill.get('skill_name') or skill.get('name')) == PUBLIC_SKILL, '指定的不是公共负载均衡 Skill')
    file_rows = records(skill.get('files', []), 'files')
    require(all(isinstance(f.get('path'), str) for f in file_rows), '公共包文件路径无法核验')
    files = {f['path']: f.get('content') for f in file_rows}
    require(len(files) == len(file_rows), '公共包文件路径重复，停止配置')
    content = text_field(skill, 'content')
    require(content.strip() and all(isinstance(files.get(p), str) and files[p].strip()
            for p in ('scripts/squad_balance.py', 'references/contract.md')), '公共 Skill 包不完整；请通过可信来源修复，不直接覆盖共享包')
    parts = content.splitlines()
    require(parts and parts[0] == '---' and '---' in parts[1:], '公共 Skill 缺少有效 frontmatter')
    frontmatter = '\n'.join(parts[1:parts[1:].index('---') + 1])
    match = re.search(r'^version:\s*[\"\']?([0-9]+(?:\.[0-9]+){2}(?:[-+][0-9A-Za-z.-]+)?)\s*[\"\']?\s*$', frontmatter, re.M)
    if match is None:
        # Portable public skills keep only name/description in frontmatter.
        body = '\n'.join(parts[parts[1:].index('---') + 2:])
        match = re.search(r'^- \*\*Version\*\*:\s*([0-9]+(?:\.[0-9]+){2}(?:[-+][0-9A-Za-z.-]+)?)\s*$', body, re.M)
    require(match, '公共 Skill 版本无法核验；先核对可信来源和安装包')
    config = skill.get('config') if isinstance(skill.get('config'), dict) else {}
    metadata = {k: config.get(k) for k in ('origin', 'source_url', 'version', 'local_patch')}
    origin = config.get('origin')
    origin_details = origin if isinstance(origin, dict) else {}
    kind = origin_details.get('type') if origin_details else origin
    source = config.get('source_url') or origin_details.get('source_url')
    source_host = urlsplit(source).hostname if isinstance(source, str) else None
    patch = config.get('local_patch')
    require(patch is None or isinstance(patch, dict), '公共包补丁来源格式无法核验')
    if patch:
        script_hash = hashlib.sha256(files['scripts/squad_balance.py'].encode()).hexdigest()
        require(patch.get('version') == match[1] and patch.get('script_sha256') == script_hash,
                '公共包补丁版本或脚本哈希不一致；先核对共享包，不自动覆盖')
    base_version = origin_details.get('version')
    if not isinstance(base_version, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}(?:[-+][0-9A-Za-z.-]+)?', base_version):
        base_version = None
    return {'id': uid(identity), 'version': match[1],
            'content_hash': digest({'content': content, 'files': files}),
            'origin': {'kind': kind if isinstance(kind, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', kind) else None,
                       'source_host': source_host, 'base_version': base_version,
                       'local_patch_version': match[1] if patch else None,
                       'metadata_hash': digest(metadata)}}



def templates():
    text = (ROOT / 'references' / 'roles.md').read_text()
    found = re.split(r'^## (project|squad|leader|worker)\s*$', text, flags=re.M)
    result = {found[i]: found[i + 1].strip() for i in range(1, len(found), 2)}
    require(set(result) == {'project', 'squad', 'leader', 'worker'}, '角色模板缺失')
    return result


def merge(original, body, project_id):
    begin = f'<!-- multica-squad-onboard:{project_id}:begin -->'
    end = f'<!-- multica-squad-onboard:{project_id}:end -->'
    markers = re.findall(r'<!-- multica-squad-onboard:([0-9A-Fa-f-]+):(begin|end) -->', original)
    require(original.count('<!-- multica-squad-onboard:') == len(markers), '项目托管标记格式未知；先人工对账')
    active, seen = None, set()
    for identity, boundary in markers:
        require(uid(identity) == identity, '项目托管标记 UUID 格式不规范；先人工对账')
        if boundary == 'begin':
            require(active is None and identity not in seen, '项目托管块嵌套或重复；先人工对账')
            active = identity
            seen.add(identity)
        else:
            require(active == identity, '项目托管块交叉或损坏；先人工对账')
            active = None
    require(active is None, '项目托管块缺少结束标记；先人工对账')
    require(original.count(begin) == original.count(end) and original.count(begin) <= 1,
            '同项目托管块重复或损坏；先人工对账，不覆盖原文')
    block = begin + '\n' + body + '\n' + end
    if begin in original:
        start, stop = original.index(begin), original.index(end)
        require(start < stop, '托管块边界损坏')
        return original[:start] + block + original[stop + len(end):]
    return original + ('\n\n' if original else '') + block + '\n'


def targets(snapshot):
    route, bodies = snapshot['route'], templates()
    desired = [('project', route['project_id'], 'description', snapshot['project']['description'], 'project'),
               ('squad', route['squad_id'], 'instructions', snapshot['squad']['instructions'], 'squad')]
    desired += [('agent', a['id'], 'instructions', a['instructions'],
                 'leader' if a['id'] == route['leader_id'] else 'worker') for a in snapshot['agents']]
    return [{'kind': kind, 'id': identity, 'field': field, 'before': before,
             'after': merge(before, bodies[role].format(project_id=route['project_id']), route['project_id'])}
            for kind, identity, field, before, role in desired]


def prepare(cli, snapshot, reviewed, skill_id):
    require(not snapshot['blockers'], '前置条件未满足；先按检查报告在 Multica 修复')
    require(stable(snapshot) == stable(reviewed), '已审阅快照过期或属于不同环境；重新 inspect 并审阅原指令')
    skill = skill_identity(cli, skill_id)
    plan = {'schema': SCHEMA, 'context': cli.context, 'snapshot': stable(snapshot),
            'skill': skill, 'targets': targets(snapshot)}
    plan['plan_id'] = digest(plan)
    return plan


def verify_plan(plan):
    require(plan.get('schema') == SCHEMA, '不支持的计划格式')
    require(plan.get('plan_id') == digest({k: v for k, v in plan.items() if k != 'plan_id'}), '计划摘要不匹配')
    require(plan['context'] == plan['snapshot']['context'], '计划环境不一致')
    require(plan['targets'] == targets(plan['snapshot']), '计划包含非托管修改或模板已改变；重新生成计划')


def reconcile(cli, plan):
    snapshot = plan['snapshot']
    current = inspect(cli, snapshot['project_id'], snapshot['squad_constraint'])
    require(not current['blockers'] and current.get('route') == snapshot['route'], '前置条件或组织关系变化，停止配置')
    require(skill_identity(cli, plan['skill']['id']) == plan['skill'], '公共 Skill 内容或来源元信息变化；重新审阅')
    fresh_targets = {(t['kind'], t['id']): t for t in targets(current)}
    for target in plan['targets']:
        text = fresh_targets[(target['kind'], target['id'])]['before']
        require(text in (target['before'], target['after']), '原指令被其他操作修改；停止，不覆盖、不自动回滚')
    prior_agents = {a['id']: a for a in snapshot['agents']}
    for agent in current['agents']:
        prior = prior_agents[agent['id']]
        require(all(agent[k] == prior[k] for k in ('runtime_id', 'capacity', 'role')), '成员运行绑定、容量或角色变化，重新审阅')
        before = {s['id']: s['enabled'] for s in prior['skill_assignments']}
        expected = dict(before)
        expected[plan['skill']['id']] = True
        current_assignments = {s['id']: s['enabled'] for s in agent['skill_assignments']}
        require(current_assignments in (before, expected), '业务 Skill 分配被改变；重新审阅')
    return current


def apply(plan_path, *, resume=False):
    plan_path = outside(plan_path)
    plan = read_private(plan_path)
    verify_plan(plan)
    cli = CLI(plan['context'])
    journal_path = plan_path.parent / (plan['plan_id'] + '.apply.json')
    journal = {'schema': SCHEMA, 'plan_id': plan['plan_id'], 'status': 'started', 'operations': []}
    if journal_path.exists():
        journal = read_private(journal_path)
        require(journal.get('plan_id') == plan['plan_id'], '日志身份不匹配')
        require(journal.get('status') == 'completed' or resume, '已有写入日志：先对账，确认后用 --reconcile 恢复')
    else:
        reconcile(cli, plan)
        write_private(journal_path, journal)
    try:
        current = reconcile(cli, plan)
        for agent in current['agents']:
            if plan['skill']['id'] not in agent['enabled_skill_ids']:
                reconcile(cli, plan)
                journal['operations'].append({'kind': 'agent_skill_add', 'id': agent['id'], 'status': 'started'})
                write_private(journal_path, journal, replace=True)
                cli.run(['agent', 'skills', 'add', agent['id'], '--skill-ids', plan['skill']['id']])
                require(plan['skill']['id'] in enabled_ids(cli.get('agent', agent['id'])), '公共 Skill 追加后读回不一致')
                journal['operations'][-1]['status'] = 'verified'
                write_private(journal_path, journal, replace=True)
        for target in plan['targets']:
            reconcile(cli, plan)
            text = text_field(cli.get(target['kind'], target['id']), target['field'])
            require(text in (target['before'], target['after']), '写前检测到并发更新，停止配置')
            if text != target['after']:
                journal['operations'].append({'kind': target['kind'], 'id': target['id'], 'status': 'started'})
                write_private(journal_path, journal, replace=True)
                cli.run([target['kind'], 'update', target['id'], '--' + target['field'], target['after']])
                require(text_field(cli.get(target['kind'], target['id']), target['field']) == target['after'], '指令写后读回不一致，先对账')
                journal['operations'][-1]['status'] = 'verified'
                write_private(journal_path, journal, replace=True)
        current = reconcile(cli, plan)
        require(all(plan['skill']['id'] in a['enabled_skill_ids'] for a in current['agents']), '公共 Skill 未全部启用')
        require(all(text_field(cli.get(t['kind'], t['id']), t['field']) == t['after'] for t in plan['targets']), '最终指令核验失败')
        journal['status'] = 'completed'
        write_private(journal_path, journal, replace=True)
        return {'status': 'configured', 'route': current['route'], 'journal': str(journal_path),
                'runtime_verification': current['runtime_verification'], 'preview': '尚未运行；调用已安装公共 Skill preview'}
    except (OnboardError, OSError, ValueError, KeyError, TypeError):
        journal['status'] = 'uncertain'
        write_private(journal_path, journal, replace=True)
        raise OnboardError('配置未完成或写入结果不确定；读取私有日志和平台对账，禁止直接重试或覆盖他人更新') from None


def set_project_lead(cli, project_id, squad_id, agent_id, record_file, *, authorized=False, resume=False):
    """Repair only the explicitly authorized project's lead; never choose a person or mutate a squad."""
    require(authorized, '设置负责人需要用户明确授权和目标；仅检查或目标不明确时不写入')
    require(squad_id, '设置负责人须指定用户已确认的小队')
    agent_id, squad_id = uid(agent_id), uid(squad_id)
    project = cli.get('project', project_id)
    require(project.get('workspace_id') == cli.context['workspace_id'] and not project.get('archived_at'),
            '项目工作区不匹配或已归档')
    squad = cli.get('squad', squad_id)
    require(squad.get('workspace_id') == cli.context['workspace_id'] and not squad.get('archived_at')
            and squad.get('leader_id') == agent_id, '目标 Agent 必须是指定有效小队的队长')
    found = [s for s in records(cli.run(['squad', 'list']), 'squads')
             if s.get('workspace_id') == cli.context['workspace_id'] and not s.get('archived_at')
             and s.get('leader_id') == agent_id]
    require(len(found) == 1 and found[0].get('id') == squad_id, '目标队长不是唯一有效小队关系；先修复歧义')
    members = records(cli.run(['squad', 'member', 'list', squad_id]), 'members')
    member_ids = [uid(x.get('member_id')) for x in members if x.get('member_type') == 'agent']
    require(agent_id in member_ids and len(member_ids) == len(set(member_ids))
            and len(set(member_ids) - {agent_id}) >= 1, '目标小队须有队长及不重复的执行成员')
    leader = cli.get('agent', agent_id)
    require(leader.get('workspace_id') == cli.context['workspace_id'] and not leader.get('archived_at'),
            '目标队长 Agent 不可用或工作区不匹配')
    before = {k: project.get(k) for k in ('lead_type', 'lead_id')}
    after = {'lead_type': 'agent', 'lead_id': agent_id}
    record_path = outside(record_file)
    identity = {'schema': SCHEMA, 'action': 'set_project_lead', 'context': cli.context,
                'project_id': project_id, 'squad_id': squad_id, 'agent_id': agent_id}
    if record_path.exists():
        record = read_private(record_path)
        require(all(record.get(k) == v for k, v in identity.items()), '负责人修复记录属于不同目标或环境')
        if before != after:
            require(resume and before == record.get('before') and record.get('status') != 'verified',
                    '已有负责人修复记录；先对账，不覆盖其他操作的新负责人')
    else:
        record = dict(identity, before=before, after=after, status='prepared')
        write_private(record_path, record)
    if before == after:
        record['status'] = 'verified'
        write_private(record_path, record, replace=True)
        return {'status': 'project_lead_verified', 'changed': False, 'project_id': project_id,
                'agent_id': agent_id, 'record': str(record_path)}
    current = cli.get('project', project_id)
    require({k: current.get(k) for k in ('lead_type', 'lead_id')} == before,
            '写入前负责人已变化，重新审阅，不覆盖')
    record['status'] = 'started'
    write_private(record_path, record, replace=True)
    try:
        cli.run(['project', 'update', project_id, '--lead', agent_id])
        current = cli.get('project', project_id)
        require(current.get('workspace_id') == cli.context['workspace_id'] and
                {k: current.get(k) for k in ('lead_type', 'lead_id')} == after,
                '负责人写后身份不一致，先对账；不能按名字猜测或继续接入')
        record['status'] = 'verified'
        write_private(record_path, record, replace=True)
        return {'status': 'project_lead_verified', 'changed': True, 'project_id': project_id,
                'before': before, 'after': after, 'record': str(record_path)}
    except (OnboardError, OSError, ValueError, KeyError, TypeError):
        record['status'] = 'uncertain'
        write_private(record_path, record, replace=True)
        raise OnboardError('负责人修复未确认完成；先读取项目和私有记录对账，不按名称盲试、不自动重试') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('profile', 'server-url', 'workspace-id'):
        parser.add_argument('--' + key)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'prepare'):
        p = sub.add_parser(name)
        p.add_argument('project', help='项目 UUID 或 HTTPS 项目 URL')
        p.add_argument('--squad-id', help='用户指定的小队 UUID/URL，仅校验不改关系')
        if name == 'inspect':
            p.add_argument('--snapshot-file', help='保存原指令等私有快照的外部路径；文件须不存在')
        else:
            p.add_argument('--reviewed-snapshot', required=True, help='已审阅原指令、业务边界及冲突的 inspect 快照')
            p.add_argument('--skill-id', required=True, help='已核验可信来源和完整包的工作区公共 Skill UUID')
            p.add_argument('--plan-file', required=True, help='新建的外部私有计划文件')
    p = sub.add_parser('set-project-lead')
    p.add_argument('project', help='项目 UUID 或 HTTPS 项目 URL')
    p.add_argument('--squad-id', required=True, help='用户已确认的小队 UUID/URL')
    p.add_argument('--agent-id', required=True, help='用户已授权设置的队长 Agent UUID')
    p.add_argument('--authorized', action='store_true', help='调用者已获得本次具体负责人变更授权；标志本身不授予权限')
    p.add_argument('--record-file', required=True, help='安装目录外的私有修复记录')
    p.add_argument('--reconcile', action='store_true', help='已经对账后恢复，仅允许原负责人未被他人更改')
    p = sub.add_parser('apply')
    p.add_argument('--plan-file', required=True)
    p.add_argument('--reconcile', action='store_true', help='人工/Agent 已对账后恢复；不绕过状态校验')
    args = parser.parse_args()
    try:
        if args.command == 'apply':
            require(not any(getattr(args, k) for k in ('profile', 'server_url', 'workspace_id')),
                    'apply 使用计划中固定的环境；不接受环境覆盖')
            result = apply(args.plan_file, resume=args.reconcile)
        elif args.command == 'set-project-lead':
            cli, project_id, squad_id = context_for(args)
            result = set_project_lead(cli, project_id, squad_id, uid(args.agent_id), args.record_file,
                                      authorized=args.authorized, resume=args.reconcile)
        else:
            cli, project_id, squad_id = context_for(args)
            snapshot = inspect(cli, project_id, squad_id)
            if args.command == 'inspect':
                if args.snapshot_file:
                    write_private(args.snapshot_file, snapshot)
                result = summary(snapshot)
            else:
                plan = prepare(cli, snapshot, read_private(args.reviewed_snapshot), uid(args.skill_id))
                write_private(args.plan_file, plan)
                result = {'status': 'prepared', 'plan_id': plan['plan_id'], 'plan_file': str(outside(args.plan_file)),
                          'target_count': len(plan['targets']), 'skill': plan['skill']}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get('blockers') else 0
    except (OnboardError, OSError, ValueError, KeyError, TypeError):
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, OnboardError) else '本地文件或响应格式错误；检查私有路径、权限与文件格式，不输出原始响应'
        print(json.dumps({'status': 'blocked', 'message': message}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())

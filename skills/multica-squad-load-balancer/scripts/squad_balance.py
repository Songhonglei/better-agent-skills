#!/usr/bin/env python3
"""Portable Multica squad scheduling. Uses installed CLI identity; stdlib only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

VERSION = '1.0.3'
COMPATIBLE_VERSIONS = {'1.0.0', '1.0.1', VERSION}
ACTIVE = {'queued', 'dispatched', 'prepared', 'running', 'claimed', 'starting'}
TERMINAL = {'completed', 'failed', 'cancelled', 'canceled', 'interrupted', 'timed_out'}
MARKER = 'MULTICA_SQUAD_BALANCE_V1 '

class BalanceError(Exception):
    pass

def require(ok, message):
    if not ok:
        raise BalanceError(message)

def uid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise BalanceError('缺少合法 UUID') from None

def rows(raw, key):
    if isinstance(raw, dict):
        require(not raw.get('has_more'), f'{key} 返回截断数据，不能可靠调度')
        for k in (key, 'items'):
            if isinstance(raw.get(k), list):
                raw = raw[k]
                break
    require(isinstance(raw, list) and all(isinstance(x, dict) for x in raw), f'{key} 返回格式无法核验')
    return raw

def private_path(value):
    path = Path(value).expanduser().resolve()
    root = Path(__file__).resolve().parents[1]
    require(path != root and root not in path.parents, '持久状态和执行绑定必须位于 Skill 安装目录之外')
    return path

def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def one(items, id_):
    found = [x for x in items if x.get('id') == id_]
    require(len(found) == 1, '任务身份无法唯一核验')
    return found[0]

class CLI:
    def __init__(self, args):
        self.base = ['multica']
        for flag, value in [('--profile', args.profile), ('--server-url', args.server_url), ('--workspace-id', args.workspace_id)]:
            if value:
                self.base += [flag, value]

    def call(self, *args, stdin=None):
        try:
            p = subprocess.run(self.base + list(args) + ['--output', 'json'], input=stdin,
                               text=True, capture_output=True, timeout=40)
        except subprocess.TimeoutExpired:
            raise BalanceError('Multica 请求超时；写入结果可能不确定，先对账，禁止直接重派') from None
        except FileNotFoundError:
            raise BalanceError('未安装 multica CLI') from None
        # CLI stderr may contain credentials or private runtime configuration.
        require(p.returncode == 0, f'Multica {" ".join(args[:2])} 失败，退出码 {p.returncode}；请检查当前身份与权限')
        try:
            return json.loads(p.stdout)
        except ValueError:
            raise BalanceError('Multica 响应不是 JSON；写入后先对账') from None

    def get(self, kind, id_):
        raw = self.call(kind, 'get', uid(id_))
        item = raw.get(kind, raw) if isinstance(raw, dict) else None
        require(isinstance(item, dict) and item.get('id') == uid(id_), f'{kind} 身份不匹配')
        return item

    def runs(self, issue_id):
        return rows(self.call('issue', 'runs', issue_id), 'task_runs')

    def comments(self, issue_id):
        return rows(self.call('issue', 'comment', 'list', issue_id), 'comments')

def resolve(cli, project_id):
    project = cli.get('project', project_id)
    require(project.get('lead_type') == 'agent' and not project.get('archived_at'), '项目必须由未归档的 Agent 负责')
    leader_id, workspace_id = uid(project.get('lead_id')), uid(project.get('workspace_id'))
    squads = [s for s in rows(cli.call('squad', 'list'), 'squads')
              if s.get('leader_id') == leader_id and s.get('workspace_id') == workspace_id and not s.get('archived_at')]
    require(len(squads) == 1, '项目队长须领导唯一有效小队；零支或多支时停止')
    squad = cli.get('squad', squads[0]['id'])
    require(squad.get('leader_id') == leader_id and squad.get('workspace_id') == workspace_id and not squad.get('archived_at'), '小队路由发生变化')
    members = rows(cli.call('squad', 'member', 'list', squad['id']), 'members')
    require(any(m.get('member_type') == 'agent' and m.get('member_id') == leader_id for m in members), '队长不在成员名单中')
    workers = [m for m in members if m.get('member_type') == 'agent' and m.get('member_id') != leader_id]
    require(workers and len({m['member_id'] for m in workers}) == len(workers), '小队须有不重复的非队长 Agent 成员')
    route = {'workspaceId': workspace_id, 'projectId': project['id'], 'leaderAgentId': leader_id, 'squadId': squad['id'],
             'members': sorted(m['member_id'] for m in workers), 'version': VERSION}
    route['routeHash'] = digest(route)
    return route, workers

def context(cli, issue_id, project_id=None):
    issue = cli.get('issue', issue_id)
    if project_id:
        require(issue.get('project_id') == project_id, 'Issue 不属于指定项目')
    route, members = resolve(cli, uid(issue.get('project_id')))
    require(issue.get('workspace_id') == route['workspaceId'] and issue.get('assignee_type') == 'squad'
            and issue.get('assignee_id') == route['squadId'], 'Issue 必须指派给项目负责人的小队')
    return issue, route, members, cli.runs(issue_id)

def verify_leader(run, route, issue_id, active=True):
    require(run.get('agent_id') == route['leaderAgentId'] and run.get('is_leader_task') is True
            and run.get('squad_id') == route['squadId'] and run.get('issue_id') == issue_id
            and run.get('workspace_id') == route['workspaceId'], '不是该 Issue 的正式队长 task-run')
    if active:
        require(run.get('status') in ACTIVE, '队长 task-run 已结束')

def candidates(cli, route, members, required_skills=(), member_role=None):
    runtimes = rows(cli.call('runtime', 'list'), 'runtimes')
    runtime_map = {r['id']: r for r in runtimes}
    result = []
    for member in members:
        agent_id = uid(member['member_id'])
        agent = cli.get('agent', agent_id)
        require(agent.get('workspace_id') == route['workspaceId'], '成员来自其他工作区')
        tasks = rows(cli.call('agent', 'tasks', agent_id), 'tasks')
        require(all(t.get('status') in ACTIVE | TERMINAL and t.get('agent_id') == agent_id for t in tasks), '成员任务状态未知或身份不匹配')
        load = len({uid(t.get('id')) for t in tasks if t['status'] in ACTIVE})
        capacity = agent.get('max_concurrent_tasks')
        runtime = runtime_map.get(agent.get('runtime_id'), {})
        skills = {s['id'] for s in rows(agent.get('skills', []), 'skills') if s.get('enabled') is True}
        reasons = []
        if agent.get('archived_at') or agent.get('status') not in {'idle', 'busy', 'working', 'running', 'active', 'online'}:
            reasons.append('Agent 不可用')
        if runtime.get('status') not in {'online', 'active', 'ready'} or agent.get('runtime_bound') is False:
            reasons.append('运行环境离线或未绑定')
        if type(capacity) is not int or capacity <= 0:
            reasons.append('并发上限无效')
        elif load >= capacity:
            reasons.append('并发已满')
        if not set(required_skills) <= skills:
            reasons.append('缺少任务所需 Skill')
        if member_role is not None and member.get('role') != member_role:
            reasons.append('角色不匹配')
        result.append({'agentId': agent_id, 'agentName': agent.get('name', agent_id), 'activeTasks': load,
                       'capacity': capacity, 'eligible': not reasons, 'excludedReasons': reasons})
    return sorted(result, key=lambda c: (c['activeTasks'], c['agentId']))

def records(comments, route, issue_id):
    result = []
    for comment in comments:
        content = comment.get('content', '')
        require(isinstance(content, str), '评论内容格式无法核验')
        for line in content.splitlines():
            if not line.startswith(MARKER):
                continue
            # Human/worker text cannot forge the leader's scheduling record.
            if comment.get('author_type') != 'agent' or comment.get('author_id') != route['leaderAgentId']:
                continue
            try:
                record = json.loads(line[len(MARKER):])
            except ValueError:
                raise BalanceError('已有队长派单标记损坏，需对账') from None
            require(isinstance(record, dict), '已有队长派单标记必须是对象，需对账')
            require(record.get('issueId') == issue_id and record.get('squadId') == route['squadId']
                    and record.get('leaderAgentId') == route['leaderAgentId']
                    and record.get('leaderTaskRunId') == comment.get('source_task_id'), '派单标记与评论来源不一致')
            record = dict(record, commentId=comment['id'])
            result.append(record)
    return result

def plan(cli, args):
    issue, route, members, runs = context(cli, uid(args.issue_id), args.project_id)
    leader = one(runs, uid(args.task_run_id))
    verify_leader(leader, route, issue['id'])
    require(not os.environ.get('MULTICA_AGENT_ID') or os.environ['MULTICA_AGENT_ID'] == route['leaderAgentId'], '当前 Agent 不是队长')
    result = {'version': VERSION, 'issueId': issue['id'], 'route': route, 'leaderTaskRunId': leader['id']}
    if issue.get('status_category') in {'done', 'canceled', 'cancelled'} or issue.get('status') in {'done', 'cancelled', 'canceled'}:
        return dict(result, action='no_action', reason='Issue 已终态')
    # Every worker run (even an untrusted direct mention) blocks automatic redispatch.
    prior = [r for r in runs if r.get('agent_id') != route['leaderAgentId'] and r.get('is_leader_task') is not True]
    comments = cli.comments(issue['id'])
    sent = records(comments, route, issue['id'])
    if prior or sent:
        return dict(result, action='no_action', reason='已有执行或派单记录；活跃、完成和失败都先对账，不自动换人',
                    existingTaskRunIds=[r['id'] for r in prior], existingCommentIds=[r['commentId'] for r in sent])
    leaders = [r for r in runs if r.get('is_leader_task') is True and r.get('status') in ACTIVE]
    require(len(leaders) == 1 and leaders[0]['id'] == leader['id'], '存在并发队长 task-run，停止派单以避免竞争')
    metadata = issue.get('metadata') or {}
    require(isinstance(metadata, dict), 'Issue metadata 格式未知')
    policy = metadata.get('multica_load_balance') or {}
    require(isinstance(policy, dict), 'multica_load_balance 必须是对象')
    require(isinstance(policy.get('requiredSkillIds', []), list), 'requiredSkillIds 必须是数组')
    required_skills = list(args.required_skill_id or []) + policy.get('requiredSkillIds', [])
    required_skills = sorted({uid(s) for s in required_skills})
    role = args.member_role or policy.get('memberRole')
    require(role is None or isinstance(role, str), 'memberRole 必须是字符串')
    loads = candidates(cli, route, members, required_skills, role)
    eligible = [c for c in loads if c['eligible']]
    if not eligible:
        return dict(result, action='failed', reason='没有在线且满足技能、角色和容量条件的成员', candidateLoads=loads)
    chosen = eligible[0]
    decision = {'issueId': issue['id'], 'projectId': route['projectId'], 'squadId': route['squadId'],
                'leaderAgentId': route['leaderAgentId'], 'leaderTaskRunId': leader['id'],
                'selectedAgentId': chosen['agentId'], 'routeHash': route['routeHash'], 'version': VERSION}
    decision['decisionId'] = digest(decision)
    return dict(result, action='dispatch_planned', selectedAgentId=chosen['agentId'], selectedAgentName=chosen['agentName'],
                candidateLoads=loads, decision=decision, reason='活跃任务数升序；并列按 Agent UUID 升序')

def dispatch(cli, args):
    try:
        import fcntl
    except ImportError:
        raise BalanceError('dispatch 需要支持 fcntl 的 POSIX 环境（Linux/macOS）') from None
    require(os.environ.get('MULTICA_TASK_ID') == args.task_run_id and bool(os.environ.get('MULTICA_AGENT_ID')),
            'dispatch 只能在真实 Multica 队长运行环境中执行；本地使用 plan/preview')
    # Local lock + pre-write journal avoids simultaneous retries on one host.
    key = digest({'server': args.server_url or os.environ.get('MULTICA_SERVER_URL'), 'profile': args.profile,
                  'workspace': args.workspace_id or os.environ.get('MULTICA_WORKSPACE_ID'), 'issue': args.issue_id})
    folder = private_path(os.environ.get('MULTICA_BALANCE_STATE_DIR', str(Path.home() / '.cache' / 'multica-squad-load-balancer')))
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = folder / (key + '.lock')
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        decision = plan(cli, args)
        outcome = decision['action']
        if outcome != 'dispatch_planned':
            cli.call('squad', 'activity', args.issue_id, outcome, '--reason', decision['reason'])
            return decision
        intent = folder / (key + '.json')
        require(not intent.exists(), '本机已有派单意图但平台未查到记录；结果不确定，需对账')
        # Recheck route, leader and capacity immediately before external write.
        current = plan(cli, args)
        require(current.get('decision') == decision['decision'], '路由或负载已改变；重新运行 plan')
        command = ['issue', 'comment', 'add', args.issue_id, '--content-stdin']
        parent = args.comment_parent_id or os.environ.get('MULTICA_TRIGGER_COMMENT_ID')
        leader_run = one(cli.runs(args.issue_id), args.task_run_id)
        verify_leader(leader_run, decision['route'], args.issue_id)
        if leader_run.get('trigger_comment_id'):
            require(not parent or parent == leader_run['trigger_comment_id'], '回复 parent 与队长触发评论不一致')
            parent = leader_run['trigger_comment_id']
        if parent:
            command += ['--parent', uid(parent)]
        state = dict(decision['decision'], state='intent')
        with os.fdopen(os.open(intent, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as file:
            json.dump(state, file)
            file.flush()
            os.fsync(file.fileno())
        name = re.sub(r'[\[\]\r\n]', '', decision['selectedAgentName'])
        body = (MARKER + json.dumps(decision['decision'], ensure_ascii=False, separators=(',', ':')) + '\n\n'
                + f'[@{name}](mention://agent/{decision["selectedAgentId"]})\n'
                + '请读取完整 Issue 和本触发评论，先使用 multica-squad-load-balancer 的 verify-worker 校验自身委派链，再执行 Issue 已授权的业务。'
                + '不再次派单，不改变小队 assignee，不另建子 Issue；输出按原业务要求回传。\n'
                + '候选负载：' + json.dumps(decision['candidateLoads'], ensure_ascii=False))
        cli.call(*command, stdin=body)
        posted = [c for c in cli.comments(args.issue_id) if c.get('author_id') == decision['route']['leaderAgentId']
                  and c.get('source_task_id') == args.task_run_id and c.get('content') == body]
        require(len(posted) == 1, '派单评论无法唯一读回；保留意图并对账，不重派')
        intent.write_text(json.dumps(dict(state, state='sent', commentId=posted[0]['id'])), encoding='utf-8')
        cli.call('squad', 'activity', args.issue_id, 'action', '--reason',
                 'load-balancer ' + decision['decision']['decisionId'] + ' ' + json.dumps(decision['candidateLoads'], ensure_ascii=False))
        return dict(decision, action='dispatched', commentId=posted[0]['id'])

def verify_worker(cli, args):
    issue, route, _, runs = context(cli, uid(args.issue_id), args.project_id)
    run = one(runs, uid(args.task_run_id))
    agent_id = uid(args.agent_id)
    require(not os.environ.get('MULTICA_TASK_ID') or os.environ['MULTICA_TASK_ID'] == run['id'], '当前 task-run 不一致')
    require(not os.environ.get('MULTICA_AGENT_ID') or os.environ['MULTICA_AGENT_ID'] == agent_id, '当前 Agent 不一致')
    require(agent_id in route['members'] and run.get('agent_id') == agent_id and run.get('status') in ACTIVE
            and run.get('is_leader_task') is not True and run.get('issue_id') == issue['id']
            and run.get('workspace_id') == route['workspaceId'], '不是本 Issue 的活跃非队长成员 run')
    # Multica comment-delegated workers omit squad_id. Derive it from the verified
    # issue assignment + official leader + delegation record below; reject explicit mismatch.
    require(not run.get('squad_id') or run['squad_id'] == route['squadId'], '成员 run 明确属于其他小队')
    attr = run.get('attribution') or {}
    require(isinstance(attr, dict), 'delegation attribution 必须是对象')
    require(attr.get('source') == 'delegation', '缺少 delegation attribution')
    leader = one(runs, uid(attr.get('delegated_from_task_id')))
    verify_leader(leader, route, issue['id'], active=False)
    sent = records(cli.comments(issue['id']), route, issue['id'])
    matching = [r for r in sent if r.get('selectedAgentId') == agent_id and r.get('leaderTaskRunId') == leader['id']
                and r.get('commentId') == run.get('trigger_comment_id')]
    require(len(sent) == 1 and len(matching) == 1, '没有唯一且对应本触发评论的公共派单记录')
    record = matching[0]
    require(record.get('version') in COMPATIBLE_VERSIONS, '派单协议版本不支持，需对账')
    recorded_route = {k: v for k, v in route.items() if k != 'routeHash'}
    recorded_route['version'] = record['version']
    require(record.get('projectId') == route['projectId'] and record.get('routeHash') == digest(recorded_route),
            '派单后项目队长或小队成员已变化，需对账')
    require(record.get('decisionId') == digest({k: v for k, v in record.items() if k not in {'decisionId', 'commentId'}}), '派单决策摘要不匹配')
    other = [r for r in runs if r.get('id') != run['id'] and r.get('agent_id') != route['leaderAgentId']
             and r.get('is_leader_task') is not True and r.get('status') in ACTIVE]
    require(not other, '同一 Issue 存在其他活跃执行者，需对账')
    identity = dict(action='verified', issueId=issue['id'], projectId=route['projectId'], squadId=route['squadId'],
                    workerAgentId=agent_id, workerTaskRunId=run['id'], leaderAgentId=route['leaderAgentId'],
                    leaderTaskRunId=leader['id'], routeHash=record['routeHash'], decisionId=record['decisionId'])
    if args.binding_file:
        path = private_path(args.binding_file)
        if path.exists():
            require(json.loads(path.read_text()) == identity, '已有执行绑定不一致，禁止换人覆盖')
        else:
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
                json.dump(identity, f)
    return identity

def main():
    parser = argparse.ArgumentParser(description='Multica 公共小队负载均衡 v' + VERSION)
    parser.add_argument('--profile')
    parser.add_argument('--server-url')
    parser.add_argument('--workspace-id')
    sub = parser.add_subparsers(dest='command', required=True)
    preview = sub.add_parser('preview', help='只读项目路由与成员负载，不派单')
    preview.add_argument('--project-id', required=True)
    preview.add_argument('--required-skill-id', action='append', default=[])
    preview.add_argument('--member-role')
    for command in ('plan', 'dispatch', 'verify-worker'):
        p = sub.add_parser(command)
        p.add_argument('--issue-id', default=os.environ.get('MULTICA_ISSUE_ID'))
        p.add_argument('--task-run-id', default=os.environ.get('MULTICA_TASK_ID'))
        p.add_argument('--project-id')
        if command == 'verify-worker':
            p.add_argument('--agent-id', default=os.environ.get('MULTICA_AGENT_ID'))
            p.add_argument('--binding-file')
        else:
            p.add_argument('--required-skill-id', action='append', default=[])
            p.add_argument('--member-role')
            if command == 'dispatch':
                p.add_argument('--comment-parent-id')
    args = parser.parse_args()
    try:
        cli = CLI(args)
        if args.command == 'preview':
            route, members = resolve(cli, uid(args.project_id))
            result = dict(action='preview', route=route, candidateLoads=candidates(cli, route, members,
                          [uid(s) for s in args.required_skill_id], args.member_role))
        elif args.command == 'verify-worker':
            result = verify_worker(cli, args)
        elif args.command == 'dispatch':
            result = dispatch(cli, args)
        else:
            result = plan(cli, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result['action'] == 'failed' else 0
    except (BalanceError, OSError, ValueError, TypeError, KeyError) as exc:
        # Do not echo filesystem contents or CLI stderr into issues/logs.
        message = str(exc) if isinstance(exc, BalanceError) else '本地数据或配置无法核验，请检查输入和私有状态文件'
        print(json.dumps({'action': 'failed', 'reason': message}, ensure_ascii=False))
        return 2

if __name__ == '__main__':
    sys.exit(main())

# 公共调度契约

- 项目负责人须领导唯一有效小队。多人队长、多小队歧义、截断数据、未知 task 状态、无法读取成员/运行环境均停止，不猜测。
- 负载统计全部 Agent 活跃 task-run，并按 run UUID 去重；终态不计负载。并发上限读取 Agent 配置，不人为调高。任务有专业分工时使用 requiredSkillIds/memberRole。
- 公共派单只处理原 Issue 第一次委派。既有 run、失败、已完成和评论已发但 run 未出现都先对账。业务结果是否通过、人工重跑和回调授权仍属于业务项目。
- `dispatch` 仅允许真实运行环境的 `MULTICA_TASK_ID/MULTICA_AGENT_ID`，要求该 Issue 恰有一个活跃正式队长 run。派单采用 `mention://agent/<uuid>`，评论来源必须是队长自身 task-run。
- 派单前重新解析路由和负载；本机锁串行化同 Issue 调度，并先保存私有意图。超时/写入不确定不自动重试。不同机器共享平台评论和 runs 查重；平台未提供原子比较更新/容量预留接口，因此本 Skill **不承诺跨机器严格 exactly-once 或跨 Issue 原子容量分配**。需要该保证的项目应使用自身原子调度锁，并调用本 Skill 的 `plan`，不依赖本地锁代替数据库锁。
- 业务目录执行绑定文件以 0600 创建，已绑定文件仅接受完全一致身份。服务端回调仍应验证自己的 task-run/Agent，不信任客户端绑定文件作为认证凭据。
- routeHash 绑定项目负责人、小队及成员集合，成员变化后旧决策暂停以复核；不默许换队长或换人。
- 开源包版本为 1.0.0；派单记录协议保持 1.0.3。当前 verify-worker 接受记录协议 1.0.0、1.0.1 和 1.0.3，并按记录协议重算路由摘要。其他版本（包括 1.0.2）停止并要求对账；不要改写旧记录或绑定绕过校验。
- 不将 Token、Cookie、Agent runtime_config 或 CLI stderr 写进输出。脚本只返回派单所需身份、负载、决策及错误类别。
- 退出码：0 = preview/plan/dispatched/verified/no_action；2 = 不可调度或执行失败。失败后按实际原因处理，无无人值守重试循环。

- 平台 comment-delegation 成员 run 可缺少 `squad_id`：小队归属必须由 Issue assignee、正式队长 run 的 squad_id、实时成员、真实派单评论来源和 attribution 链共同证明；显式错误 squad_id 仍拒绝。

## CLI 与环境配置

全局参数放在子命令之前。需要已安装 `multica` CLI、当前身份有项目/小队/成员/runs/评论读取权限；派单还需要真实队长评论及 squad activity 写入权限。`dispatch` 使用 POSIX `fcntl` 本机锁，仅支持 Linux/macOS 等兼容系统；其他子命令不依赖该锁。

| 参数 | 命令 | 默认 / 行为 |
|---|---|---|
| `--profile` | 全局 | 当前 CLI profile；可选 |
| `--server-url`、`--workspace-id` | 全局 | 沿用 CLI 配置/运行环境；可选，不改变正式记录身份校验 |
| `--project-id` | preview | 必填项目 UUID |
| `--project-id` | plan/dispatch/verify-worker | 可选，传入后严格检查 Issue 属于该项目 |
| `--issue-id` | plan/dispatch/verify-worker | 默认 MULTICA_ISSUE_ID；缺失时须显式传入 |
| `--task-run-id` | plan/dispatch/verify-worker | 默认 MULTICA_TASK_ID；缺失时须显式传入。dispatch 必须匹配真实运行环境 |
| `--required-skill-id` | preview/plan/dispatch | 可重复 Skill UUID；plan/dispatch 与 metadata.requiredSkillIds 合并 |
| `--member-role` | preview/plan/dispatch | 可选，字符串精确匹配小队角色；plan/dispatch 优先于 metadata.memberRole |
| `--comment-parent-id` | dispatch | 可选触发评论 UUID；默认 MULTICA_TRIGGER_COMMENT_ID。正式队长 run 存在 trigger_comment_id 时以其为准，冲突或非法值在写意图前拒绝 |
| `--agent-id` | verify-worker | 默认 MULTICA_AGENT_ID；缺失时须显式传入 |
| `--binding-file` | verify-worker | 省略时仅校验并输出身份；开始业务应按 SKILL.md 指定外部业务目录的私有绑定文件，父目录须存在 |

运行环境注入 MULTICA_TASK_ID/MULTICA_AGENT_ID；存在时必须与所校验身份一致。MULTICA_ISSUE_ID 为可选输入便利，MULTICA_SERVER_URL/MULTICA_WORKSPACE_ID 可由 CLI 配置或显式参数提供，不是必须人工设置的秘密。不要把令牌写入参数或包内。

MULTICA_BALANCE_STATE_DIR 可选覆盖本机私有状态目录，默认 `~/.cache/multica-squad-load-balancer`；目录新建权限 0700，锁/意图文件新建权限 0600。状态目录和绑定文件解析符号链接后必须在 Skill 安装目录之外，不能随更新删除。修正无效 parent 后可重试；远端写入开始后的不确定结果必须先对账。

---
name: multica-squad-load-balancer
description: >
  Multica 小队公共负载均衡。小队 Issue 由队长按实时活跃任务数、运行环境、并发容量和所需技能委派一名成员；成员校验委派链后执行原业务。用于小队派单、成员接单、重复唤醒对账和负载预览，适用于任意项目。
---


# Multica 小队负载均衡

- **Version**: 1.0.0
- **License**: MIT
- **Author**: Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)
- **Repository**: https://github.com/Songhonglei/better-agent-skills

队长和成员安装同一份 Skill。使用已有 Multica CLI 登录及运行环境身份，仅依赖 `python3` 标准库；实际派单需要 Linux/macOS 等支持 `fcntl` 的 POSIX 环境。无额外数据库或业务系统依赖，不需要共享 Token。项目负责人应为 Agent，且在同一工作区领导唯一未归档小队；Issue 应指派给该小队。直接指派个人的 Issue 按原业务执行，不强行转换。

每次处理小队 Issue 时先读取完整 Issue、触发评论和自己的 task-run。通过 `is_leader_task`、项目负责人和实时小队名单判断角色；不得凭 Agent 名称判断。命令中的脚本路径相对于本 Skill 目录，应使用安装位置的真实绝对路径，不复制脚本到业务项目。

## 队长

1. 首次派单运行：

   ```bash
   python3 <skill目录>/scripts/squad_balance.py plan --issue-id <当前Issue UUID> --task-run-id <自身 MULTICA_TASK_ID>
   python3 <skill目录>/scripts/squad_balance.py dispatch --issue-id <当前Issue UUID> --task-run-id <自身 MULTICA_TASK_ID>
   ```

   `plan` 只读，`dispatch` 在真实队长运行环境中重算并派单。CLI 的 `--profile`、`--server-url`、`--workspace-id` 参数须放在子命令前；通常沿用运行环境默认配置，禁止固定为创建者的 profile 或服务器。

2. 调度根据当前项目负责人解析小队，排除队长、非 Agent、归档/不可用/离线/达到并发上限的成员，按 `queued/dispatched/prepared/running/claimed/starting` 的任务数升序选人；并列按 Agent UUID 升序。跨项目任务也计入该 Agent 的负载。`working` 是正常可接单状态，是否满载由活跃任务数与并发上限判断。
3. 业务需要特定技能或角色时，从原 Issue 已授权要求确定条件。用重复参数 `--required-skill-id <工作区 Skill UUID>`、`--member-role <小队角色>`，或 Issue metadata 中的 `multica_load_balance: {"requiredSkillIds": [...], "memberRole": "..."}`。两条命令使用相同条件；成员异质时必须先限制能力再比较负载，不凭空替换业务 Skill。
4. `dispatched`：脚本已经在原 Issue 发出真实 mention，保存决策标记并记 squad activity；不要再手工发一次。保持小队 assignee，不创建子 Issue，队长不代做业务。
5. `no_action`：已有成员 run/派单/终态时不重派。读实际结果，按原业务流程处理。`failed`：说明离线、容量、身份或不确定结果的真实卡点；不自行换人重试。脚本写入失败后先读评论和 runs 对账，不能直接删除私有意图文件重跑。
6. 再次唤醒先辨别诉求。致谢、成员已交付、等待人工或系统自动推进时不派单。用户明确要求续跑或重新执行，先核对上一执行、副作用及未完成处；本版不自动重开已派 Issue，应由项目原有受控续跑机制处理。

## 成员

1. 只执行原 Issue 已授权任务，不递归调度。优先从运行环境取 `MULTICA_TASK_ID`、`MULTICA_AGENT_ID`，缺失时先读取当前上下文并唯一核验，不能挑选他人的 run。
2. 开始业务前运行：

   ```bash
   python3 <skill目录>/scripts/squad_balance.py verify-worker \
     --issue-id <当前Issue UUID> --task-run-id <自身run UUID> --agent-id <自身Agent UUID> \
     --binding-file <业务目录中的私有执行绑定.json>
   ```

   返回 `verified` 后执行原业务 Skill。脚本验证同项目、原小队、正式队长 run、delegation attribution、由队长真实发布的决策、选中者和触发评论，并拒绝其他活跃执行者及绑定覆盖。平台委派成员 run 可缺少 `squad_id`，此时以 Issue 小队归属、正式队长 run 和完整委派证据核验；有显式 `squad_id` 时必须一致。历史委派没有公共决策标记时走项目原有校验，不伪造标记。
3. 在自身触发评论线程回传真实结果，保持原业务的状态决策、输出、审批与权限规则。不将 run completed 当作业务成功。`verified` 只证明调度身份，不授予业务权限，也不替代原业务 claim/回调的服务端绑定。

开源包版本与派单记录协议分别管理：本包 v1.0.0 保留脚本的记录协议 1.0.3，避免改变已有路由摘要。可验证的记录协议版本及不支持版本的对账行为见 contract。

## 安装与预览

完整 Skill 包导入 Multica 工作区后，通过 `multica agent skills add <Agent UUID> --skill-ids <公共Skill UUID>` 追加给队长及所有执行成员，无须改写 Agent 原有业务 Instruction。新增成员同样追加安装。Skill 中没有项目、小队或成员固定 ID。

```bash
python3 <skill目录>/scripts/squad_balance.py preview --project-id <项目UUID>
```

`preview` 只读路由与负载。完整参数、可选环境覆盖、运行前提、并发和恢复边界，见 [references/contract.md](references/contract.md)。持久状态及业务绑定必须放在本 Skill 安装目录之外。

## Changelog

See [CHANGELOG.md](./CHANGELOG.md).

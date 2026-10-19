---
name: multica-squad-onboard
description: >
  根据 Multica 项目 ID 或 URL 检查现有小队前提，安装公共负载均衡 Skill，配置项目、小队及不同角色的项目作用域 Instruction，并只读验收。当用户要求小队首次接入、配置复查或补装时使用；实际业务派单使用 multica-squad-load-balancer。
---


# Multica 小队接入

- **Version**: 1.0.0
- **License**: MIT
- **Author**: Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)
- **Repository**: https://github.com/Songhonglei/better-agent-skills

用户只需提供项目 ID 或 URL。队长、成员、业务 Skill 和分工从现有配置读取；不要求重复填表，不擅自选择负责人；用户明确目标和授权后可通过 CLI 设置项目负责人。不创建小队、不增删成员、不更换 Runtime、不修改容量或权限。用户另行提供的小队 ID/URL是校验约束，不能绕过“负责人领导唯一有效小队”的前提。

## 检查与前置设置

1. 读取项目定位信息、当前登录环境及用户已明确的操作范围。“检查”只读；“接入/配置”允许完成该项目的安装和指令配置，不代表发布 Skill、业务派单或部署代码。URL 用同源服务器查证；仅 ID 使用当前 CLI 配置。服务器或工作区存在歧义时集中询问，不猜测域名映射。
2. 执行 [scripts/onboard.py](scripts/onboard.py) 的 `inspect`，将快照保存到安装目录外。脚本核验项目负责人是 Agent、同工作区唯一未归档小队、队长在成员中、至少一名非队长 Agent，以及成员与 Runtime 配置。读 [references/operations.md](references/operations.md) 的参数、安装和恢复流程。
3. 有阻断条件时，返回具体对象、问题和 Multica 设置位置。目标未知时由用户确定负责人/队长/成员，登录和权限申请仍由用户完成。用户已明确目标并授权负责人变更时，直接调用 `set-project-lead` 设置，不要求用户再手工操作或重复确认；只读检查不能执行该修复。修复后重新读取，不能仅凭“已完成”判定通过。离线、容量无效、缺少明确业务能力的成员单列；不自行提高容量或补装业务 Skill。
4. 业务能力只按项目/任务明确声明核验，未声明时不编造必需 Skill 或角色，也不把未配置专业分工当阻断。异质成员不要求装相同业务 Skill。正式任务的能力筛选交给队长与公共 Skill。

## 安装与指令配置

1. 从当前工作区查找唯一 `multica-squad-load-balancer`。核验完整包、版本及 用户认可的可信来源；不存在时走已授权的可信来源安装流程，详见 operations 的“公共 Skill 安装”。保留已有分配。已有同名包来源不明、版本冲突或不完整时先报告；覆盖会影响其他项目，未授权不覆盖。
2. 阅读私有快照中的项目说明、Squad/Agent 指令，查找手工选人、重复 mention、队长代做、自动换人重派等冲突。不要机械追加相反规则。未托管的冲突先提出精确修改，只有已授权才修改；组织关系不擅改，已授权的负责人修复按前述流程执行。Agent 可能跨项目任不同角色，Squad 也可能被复用。
3. 使用 [references/roles.md](references/roles.md) 的项目作用域模板。`prepare` 生成私有变更计划，保留托管块外原文；`apply` 只允许项目 description、Squad/Agent instructions 和公共 Skill 的追加分配。重复执行更新同项目块，不重复追加。不修改原业务 Skill、模型、Runtime、容量、审批或状态规则。
4. 应用前展示具体变更摘要；已有“接入/配置”授权时直接继续，不为常规步骤重复确认。检查模式不能执行 apply 或 set-project-lead；组织角色选择、额外覆盖或外部操作仍需对应授权。写后读回；部分失败或结果不确定先对账，按 operations 恢复，不盲目重试或自动回滚他人修改。

## 验收与交付

- 再次 inspect，并核对计划内字段、Skill 分配、完整包和组织关系；运行同安装版本公共 Skill 的 `preview --project-id <UUID>`。只有原业务明确要求时才加 `--required-skill-id` / `--member-role`。不调用 `plan`、`dispatch`、`verify-worker`，不创建测试 Issue；用户另外授权真实业务测试时才按公共 Skill 处理。
- 在当前会话、工作目录及项目关联信息中发现代码和任务入口；先核对与目标项目的关联，不因当前目录有代码就默认属于该项目，再检查相关入口的重复调度规则；找不到标“未检查”，不要求必须提供仓库，不将局部检查描述为全覆盖。改代码/发布/部署不属于默认接入范围。
- 分别报告：配置完成、Runtime 实测情况、公共预览结果、业务端到端是否测试。平台已启用不等于远端已落盘可执行；本机 CLI/Python 成功不能证明成员 Runtime 就绪。
- 输出项目/小队/角色、公共 Skill 版本与来源、具体改动、可用成员与排除原因、缺失条件和证据位置。名单及容量为当次快照，不固化到调度配置。

## 依赖与边界

接入辅助脚本仅依赖 Python 3.10+ 标准库及已登录的 `multica` CLI；使用当前身份，不索取或共享 Token。运行公共预览需要已安装的 `multica-squad-load-balancer`；正式队长派单另需 POSIX `fcntl` 和真实 Multica run 身份，不能由接入环境伪造。Hub 下载权限和各成员业务权限独立核验。

快照、计划、日志保存在 Skill 安装目录之外，私有文件 0600；不保存 CLI stderr、Token、Cookie 或 runtime_config。未授权的项目关系、历史 Issue assignee、原评论线程、服务端 claim/回调、原业务幂等和跨机器并发保护均保留。公共 Skill 不承诺跨机器严格 exactly-once 或跨 Issue 原子容量预留。

## Changelog

See [CHANGELOG.md](./CHANGELOG.md).

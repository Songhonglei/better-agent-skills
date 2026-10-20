# 运维与日常使用

## 文件入口

默认状态根 `~/.openviking-projects`，可用前置 --home 或 OVK_HOME 修改。目录内容：

- configs/ov.conf、service.json：服务配置；provider-keys.json、root.key：本机私有凭据。
- configs/projects.json：项目与账号、工作区、scope 注册表；scheduled-projects.json：单独的定时启用清单。
- projects/<code>/configs/pilot-policy.json：该项目白名单。
- projects/<code>/curated/<code>/current/：精选原文的当前只读链接。
- projects/<code>/evidence/source-manifest.json：来源、选区、指纹；import-receipt.json：已完成导入回执。
- projects/<code>/evidence/scheduled-sync-last.json：本轮结果；sync-journal.json：提交/恢复任务记录。
- evidence/scheduled-sync-all-last.json：多项目本轮汇总。不要把旧时间的结果当成本轮成功。

OpenViking 的 abstract/overview 是生成线索，原文以 source 包和本地源文件为准。不要手改 prepared、immutable snapshots 或底层服务数据库。

## 服务和同步

```sh
python3 <skill>/scripts/ovk.py status
python3 <skill>/scripts/ovk.py start
python3 <skill>/scripts/ovk.py project sync demo --dry-run
python3 <skill>/scripts/ovk.py project sync demo
python3 <skill>/scripts/ovk.py sync-all
```

sync-all 只执行已启用列表，不自动执行所有注册项目。每项目每轮最多五份变更（包括移除），首次建库例外；超限先审阅与合理分批，不偷偷放宽限制。不变结果是 unchanged，模型任务为零。凭据只注入服务进程，MCP 子进程不读取服务 root key 或模型凭据。

同步使用共用 writer 锁和项目读写锁，提交结果写 journal，完成后逐份原文 SHA256 回读。运行中继续等同一进程；unknown 先核对已提交 task 与 journal，不重提。failed/partial 必须逐项目核对，already_running 跳过，不能算成该项目完成。

白名单移除仅允许删除本程序拥有且哈希匹配的目标；出现额外文件/子目录或来源冲突时拒绝。删除源文件但没有审阅更新 policy 会被阻断，而不是自动扩大或猜测白名单。

## 登录启动与工作日调度

用户有此需求时才启用，先给出生成内容：

```sh
python3 <skill>/scripts/ovk.py autostart
python3 <skill>/scripts/ovk.py autostart --apply
python3 <skill>/scripts/ovk.py schedule --enable demo
python3 <skill>/scripts/ovk.py schedule --enable demo --at 12:30 --timezone Asia/Shanghai --apply
```

只有已通过 verify 的项目可以加入定时列表。macOS 创建带状态根指纹的 LaunchAgent；Linux/WSL2 使用 systemd user 单元。系统任务每分钟做轻量时钟判断，真正的同步只在所选时区工作日目标分钟触发，每日期最多自动尝试一次，不因失败自动重试。脚本不修改系统时区。电脑休眠/关机或用户服务不可运行时不能保证执行；默认不补跑错过的时间，也不声称系统任务已经在未来成功运行。

该系统调度与 Codex heartbeat 是可选的两种入口，不能同时给同一实例装重复时钟。若目标环境已经有 Codex automation，优先更新现有任务，只运行一次 `venv/bin/python scripts/manage.py sync-all`，按上文回执验收并在 unchanged 时保持安静。

调整列表使用 schedule --enable/--disable；从定时列表停用项目不会删除资料、凭据或共用服务。停用所有计划项目可保留只读服务。系统任务本身的卸载应针对生成的具体 label/unit，保留其他用户任务。

## 客户端与跨电脑

全局 MCP 名称为 `openviking`，只有 resolve_project/find/read/list/tree。默认只向 `${CODEX_HOME:-~/.codex}/config.toml` 注册一次；新增项目只更新注册表和白名单，不新增 MCP。resolve_project 根据绝对工作区解析 code，每次其余调用都校验 project_code、workspace_path 和 URI scope。一个 MCP 可以路由多个独立账号，共用进程与账号隔离是两个层次。

配置追加后在客户端重新加载/新开会话；项目级配置可能覆盖全局设置，升级时需检查旧 `openviking_projects` 注册，避免重复加载。工具拒绝覆盖不匹配的全局 `openviking`，也不自动改变工作区信任级别。不能用会话内的 /mcp 状态文字代替真实工具调用。

本机默认并不把知识同步到另一电脑。另一电脑拿到项目文档、干净 Skill 包和自己可用的模型凭据后重新注册路径、建索引。服务状态、凭据、chat/session 和原始评测产物不要放进 Skill ZIP。共享一个远程服务、TLS、访问控制、资料驻留和停机迁移需要独立方案及明确授权。

[官方 Codex 集成](https://docs.openviking.ai/en/agent-integrations/04-codex)另包含会话 recall/capture hooks；本包提供项目资料 MCP，不默认启用这些聊天记忆功能。用户需要时再独立安装和审阅。

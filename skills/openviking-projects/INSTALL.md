# 在其他电脑使用

将干净的 openviking-projects ZIP 解压到 Codex 的 Skills 目录，使目录结构为：

```text
~/.codex/skills/openviking-projects/SKILL.md
~/.codex/skills/openviking-projects/scripts/ovk.py
~/.codex/skills/openviking-projects/assets/runtime/
```

保留原有 Skills，避免多套同名目录。新开会话，输入：

```text
使用 $openviking-projects，在这台电脑安装 OpenViking 并接入当前项目。
先检查已有环境，GitHub 不通时使用可信镜像。
模型服务使用我本机指定的配置；不要让我把密钥贴到聊天里。
完成白名单审阅、模型权限探针和真实 MCP 验收，再按我确认的要求设置自启动与同步。
```

也可直接从本目录运行：

```sh
python3 scripts/ovk.py preflight
python3 scripts/ovk.py install --index tuna --dry-run
```

安装和项目接入的完整流程在 references/onboarding.md。默认固定 OpenViking 0.5.0，使用外部独立状态目录 `~/.openviking-projects`；不会携带原电脑的项目、密钥、数据库、虚拟环境或聊天。安装依赖、tokenizer 编码表和模型访问仍需就绪，说明见 references/network-install.md。

本包附加脚本支持 macOS/Linux，Python 3.11+；Windows 用 WSL2。Linux/WSL2 的系统任务需要可用 systemd user 会话。其他 OS 尚需实际安装验收；当前已验证 macOS 上的隔离运行与本机假模型链路，未把已有依赖复用测试当成全新系统下载验收。

本目录仅是安装、检索和运维 Skill，不是知识数据同步包。另一电脑重新登记实际项目路径和凭据后索引自己的白名单文档。默认只注册一个全局 `openviking` MCP，所有项目按 code 和工作区路由。当前电脑若已有 OpenViking，请先复用已有管理入口，不为试用这个 Skill 改装已有部署。

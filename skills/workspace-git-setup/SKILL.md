---
name: workspace-git-setup
version: 1.0.3
description: 为任意工作区初始化并维护 Git 版本追踪，预置通用安全实践 .gitignore 规则（敏感凭证/TLS与SSH私钥/token、运行时缓存与PID、node_modules、Python缓存、构建产物、编辑器临时文件等）。支持三种模式：①初始化（git init + 安全 .gitignore + 大文件预警 + 首次 commit）；②巡检模式 --audit（只读检测已 tracked 的敏感文件、未跟踪文件、core.autocrlf 配置）；③预览模式 --dry-run（不落地预览所有改动）。自动从环境变量 GIT_AUTHOR_NAME / GIT_AUTHOR_EMAIL 或已有 git config 读取身份，读不到时引导手动输入；自动设置 core.autocrlf=input 统一换行符避免 CRLF 假 diff。工作区路径优先级：命令行参数 > 环境变量 WORKSPACE_DIR > 当前目录。当用户说以下任意一种时触发：「给项目加 git」「初始化 git」「git init」「记录我的改动」「追踪变更历史」「保存历史版本」「项目怎么做版本管理」「我改了很多东西怕丢，帮我备份」「检查 git 有没有问题」「巡检 git」「有没有敏感文件进 git」「检测漏跟踪的文件」「.gitignore 规则过期了」「修复 git 配置」「workspace git setup」「workspace-git-setup」，以及任何表达"想对工作区做版本追踪/历史记录/防丢失/git 健康检查"意图的语句。
---

# workspace-git-setup

为任意工作区一键配置并维护 Git 版本追踪，预置通用安全实践规则。

## 使用方式

```bash
# 初始化 / 对齐配置（默认当前目录，自动用目录名作为项目名）
bash scripts/setup.sh

# 指定工作区路径与项目名
bash scripts/setup.sh /path/to/project "MyProject"

# 巡检模式（只读，不改任何东西）：检测敏感文件 / 未跟踪文件 / 配置
bash scripts/setup.sh --audit

# 预览模式（dry-run，不落地）：看一遍将做的所有改动
bash scripts/setup.sh --dry-run
```

## 路径与身份解析

| 项 | 优先级 |
|----|--------|
| 工作区路径 | 命令行参数 > 环境变量 `WORKSPACE_DIR` > 当前目录 |
| Git 身份 | 环境变量 `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL` > 已有 git config > 手动输入 |

> 提供了邮箱但没提供用户名时，自动用邮箱前缀作为用户名（可后续 `git config` 修改）。

## 三种模式

| 模式 | 作用 | 是否改动 |
|------|------|----------|
| 默认（初始化/对齐） | git init + 写安全 .gitignore + 大文件预警 + 首次 commit | ✏️ 会改 |
| `--audit` | 检测①已 tracked 的敏感文件 ②未跟踪文件 ③core.autocrlf 配置 | 👀 只读 |
| `--dry-run` | 预览初始化将做的所有改动，不落地 | 👀 只读 |

## 执行流程（默认模式）

1. **确定路径**：命令行参数 > `WORKSPACE_DIR` > 当前目录
2. **推断项目名**：用工作区目录名（可用第二个参数覆盖）
3. **读取身份**：环境变量 → 已有 git config → 手动输入
4. **git init**：已有仓库则跳过（幂等）；并设置 `core.autocrlf=input` 统一换行符
5. **写入 .gitignore**：已有则展示 diff，由用户决定是否覆盖
6. **大文件预警**：扫描将纳入跟踪的 >10MB 文件，列出让用户确认再提交
7. **首次 commit**：自动暂存并提交
8. **汇总提示**：显示项目名、路径、git 身份、巡检用法

## .gitignore 默认规则（通用安全实践）

| 类型 | 规则 |
|------|------|
| 敏感凭证 | `.env`, `.env.*`, `*.pem`, `secrets/`, `.credentials/`, `*token*.json`, `*secret*.json` |
| TLS / SSH 私钥 | `**/certs/*.key`, `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519`, `*.p12`, `*.keystore` |
| 临时/缓存 | `tmp/`, `*.tmp`, `*.cache`, `*.log`, `*.pid` |
| 系统/编辑器 | `.DS_Store`, `._*`, `Thumbs.db`, `.vscode/`, `.idea/`, `*.swp` 等 |
| 依赖 | `node_modules/`, `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `.pytest_cache/` |
| 构建/生成物 | `output/`, `dist/`, `build/`, `out/`, `*.egg-info/` |

## 巡检模式（--audit）说明

只读运行，输出三类体检结果，**不自动修改**：

1. **敏感文件检测**：列出已被 git 跟踪的私钥/token/凭证类文件（泄露风险），只报警、给出人工核实建议，不给执行命令
2. **未跟踪检测**：列出未 add 且未被 .gitignore 排除的文件，提示 add 或忽略
3. **配置检测**：`core.autocrlf` 是否为推荐值、`.gitignore` 是否存在

## 注意事项

- 纯本地 Git，无远程仓库；如需备份，自行配置 remote（`git remote add origin <url>`）
- 脚本幂等，可重复运行，不会破坏已有配置
- `.gitignore` 已存在时会展示 diff，由用户确认是否覆盖
- 巡检发现敏感文件**只报警不自动处理**，由你人工核实后再决定如何移除

## 依赖

- `git`（核心依赖，必须）— https://git-scm.com/downloads
- `bash`（4.0+，脚本运行环境）
- `coreutils`（`numfmt`/`stat`/`realpath`，大文件人性化显示）— 类 Unix 系统通常内置；`numfmt` 缺失仅影响大小显示格式（降级为原始字节数），不影响功能

> 纯 bash + git 实现，无需 Python 或任何第三方包。

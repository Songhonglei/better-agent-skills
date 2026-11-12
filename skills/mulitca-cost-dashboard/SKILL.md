---
name: mulitca-cost-dashboard
description: >
  Install, configure and troubleshoot a standalone Multica cost dashboard on a
  server or computer with the Multica CLI. Collect all-workspace runtime, issue
  and task usage, estimate model costs, maintain versioned prices and inspect
  attribution gaps. Use when installing or managing the Multica companion dashboard and its collectors.
---

# Multica 费用大盘

- **Version** 1.0.0
- **License** MIT
- **Author** Evan Song · [GitHub](https://github.com/Songhonglei)
- **Repository** [better-agent-skills](https://github.com/Songhonglei/better-agent-skills)

在装有 Multica 的机器上部署独立费用大盘。应用源码和锁文件位于
[assets/dashboard](assets/dashboard)，安装和配置见 [README.md](README.md)。
版本记录见 [CHANGELOG.md](CHANGELOG.md)。

## 依赖

- Node.js 22.16+、npm、Git。
- PostgreSQL（配套镜像为 17）。可使用已有独立数据库，也可用 Docker Compose 启动配套数据库。
- 已安装并登录的 `multica` CLI，具备当前 Workspace 的 Usage 读取权限。
- Linux、macOS，Windows 通过 WSL2 使用。执行采集的系统账号需能读取自己的 Multica 配置。

## 执行流程

1. 在用户选定的应用目录复制 `assets/dashboard`，在副本运行 `npm ci`。
   应用目录应位于 Skill 安装目录外，更新 Skill 后继续保留应用配置和数据。
2. 运行 `npm run setup` 生成 `.env` 及独立管理员和采集密钥文件。
   复用已有数据库时修改 `.env` 的 `DATABASE_URL`，使用专门的空数据库。
   setup 遇到已有配置或密钥会停止，保留现有文件。
3. 在 `.env` 设置 `MULTICA_PROFILE`。留空时使用 Multica CLI 当前默认配置。
   通过 `multica runtime list --output json` 验证当前账号及 Workspace。
   指定 profile 时在命令中加入 `--profile <name>`。
4. 启动数据库后依次运行 `npm run build`、`npm run migrate`、`npm start`。
   浏览器打开默认地址 `http://127.0.0.1:4318`，用户名为 `admin`，密码来自
   `.env` 指定的 `ADMIN_SECRET_FILE`。将密码留给用户在本机查看。
5. 获得用户对当前 Workspace 数据采集的授权后，在另一终端运行
   `npm run collect -- --days 2`。首次补历史可使用 `--days 365`。
   采集日志须收到 `Committed usage snapshot`，并且 `failures=0`。
6. 在页面“价格设置”维护每百万 Token 的单价及生效日期。预估费用随价格重新计算。
   样例价格仅用于说明导入格式，正式价格由用户提供。

采集覆盖当前 profile 的全部 Workspace 项目。一个数据库对应一个 Workspace。
切换 Workspace 时使用另一个应用副本、数据库、配置和密钥。

## 验证与恢复

- `/health` 返回 `status=ok` 表示进程和数据库连通。确认页面能读取费用和保存价格。
- 部分源失败时，成功数据仍可提交，进程返回非零。检查当前 Multica 权限，修复后重跑同一采集命令。
- 上传中断时，最后完整快照仍在数据库。重新执行采集可完成新的原子提交。
- 相同快照重复上传保持幂等。V2 分块全部到齐后，按成功 Runtime 和日期范围替换数据。
- HTTP 401 检查采集密钥与机器时间，403 检查 Multica Usage 权限，413 检查两端请求大小限制。
- 使用 README 的调度命令前先完成一次手动采集。用户要求持续运行时再配置对应机器的进程管理和定时任务。

## 数据与访问

默认监听回环地址。远端使用 SSH 隧道，或配置带 HTTPS 的反向代理。
页面使用独立 Basic 登录，采集使用 HMAC 签名和 PostgreSQL nonce 防重放。
管理员密码与采集密钥分别保存在权限为 400/600 的文件，运行数据位于应用和用户数据目录。

费用按 Issue 全生命周期用量计算，Task 补齐缺口，Runtime 用于对账。
日期筛选、累计 Issue 用量和 Runtime 日用量的边界见 README 的“统计口径”。
部署成功、采集完成和费用核验分别报告。Token 缺少价格时保留为未定价。

# Multica 费用大盘

A self-hosted cost dashboard companion for Multica. Includes the web UI,
PostgreSQL backend and an all-workspace collector for machines running the Multica CLI.

按智能体、项目、发起人和模型查看预估费用、四类 Token、趋势及归因缺口。
支持价格版本、批量导入、汇率设置、深浅主题和手机浏览。

目录名沿用 `mulitca-cost-dashboard`，产品名为 Multica。

## 安装

需要 Node.js 22.16+、npm、已登录的 Multica CLI，以及 PostgreSQL（配套镜像为 17）。
支持 Linux、macOS 和 Windows WSL2。

```bash
git clone https://github.com/Songhonglei/better-agent-skills.git
cp -R better-agent-skills/skills/mulitca-cost-dashboard/assets/dashboard "$HOME/mulitca-cost-dashboard"
cd "$HOME/mulitca-cost-dashboard"
npm ci
npm run setup
```

setup 创建当前目录的 `.env`，并在 `~/.local/share/mulitca-cost-dashboard`
创建两个独立密钥文件。配置文件和密钥均为 600 权限。
再次安装可在执行 setup 前设置 `DASHBOARD_DATA_DIR` 为另一个绝对路径。

已有配置时，setup 会停止并提示保留配置或另选安装目录。
更新时将新版源码复制到应用目录，保留 `.env`、外部密钥和数据库，再运行
`npm ci`、`npm run build`、`npm run migrate` 并重启服务。

### 启动数据库和大盘

使用配套数据库时，先安装 Docker 和 Compose，再执行

```bash
docker compose up -d --wait db
npm run build
npm run migrate
npm start
```

使用已有 PostgreSQL 时，将 `.env` 中的 `DATABASE_URL` 改为专用空数据库地址，
然后从 build 开始执行。迁移仅作用于该连接指向的数据库。

打开 `http://127.0.0.1:4318`。浏览器登录用户名为 `admin`，密码保存在
`.env` 的 `ADMIN_SECRET_FILE` 路径。本机读取该文件后输入浏览器登录框。

通过 `http://127.0.0.1:4318/health` 检查服务及数据库连通性。

### 接入 Multica

应用通过当前系统账号执行 Multica CLI，CLI 自己读取登录配置。
在 `.env` 设置 `MULTICA_PROFILE`，留空则沿用 CLI 的当前默认配置。
先确认 CLI 能读取目标 Workspace 的 Runtime 列表与 Usage。

```bash
multica runtime list --output json
# 如果配置了命名 profile，加入 --profile <name>

# 在另一个终端的应用目录执行
npm run collect -- --days 2
# 首次历史回填，最多 365 天
npm run collect -- --days 365
```

当日志显示 `Committed usage snapshot` 且 `failures=0` 时，完整上传和源采集均成功。
部分源失败会返回非零并保留诊断快照，成功的范围仍可提交。
修复账号权限或 CLI 可用性后，重跑原命令。

进入“价格设置”，添加模型价格及生效日期。价格以每百万 Token 计，
支持 USD、CNY 及统一 CNY/USD 汇率。界面内 JSON 是虚构样例，导入前替换模型、价格和日期。

## 配置

`.env` 由 setup 创建。环境中已设置的同名变量优先。

| 变量 | 用途及默认值 |
| --- | --- |
| `DATABASE_URL` | 必填，专用 PostgreSQL 连接。setup 配合 Compose 生成本地连接 |
| `POSTGRES_PASSWORD` | Compose 数据库密码，由 setup 随机生成 |
| `ADMIN_SECRET_FILE` | 必填，浏览器管理员密码文件，至少 32 字符 |
| `INGEST_SECRET_FILE` | 必填，HMAC 采集密钥文件，至少 32 字符。远端采集端需配置同一密钥 |
| `HOST` | 服务监听地址，默认 `127.0.0.1` |
| `PORT` | 服务端口，默认 `4318` |
| `COST_DASHBOARD_URL` | 必填，大盘 HTTP(S) origin，setup 设为 `http://127.0.0.1:4318/` |
| `MULTICA_BIN` | CLI 可执行文件，默认 `multica` |
| `MULTICA_PROFILE` | CLI profile，默认留空，使用 CLI 当前配置 |
| `USAGE_LOOKBACK_DAYS` | 回看天数，默认 `2`，范围 `1–365` |
| `USAGE_SNAPSHOT_PATH` | 诊断快照路径，默认 `~/.local/share/mulitca-cost-dashboard/usage.json` |
| `MAX_PAYLOAD_BYTES` | 请求大小上限，默认 `67108864`，服务端允许 `1–100 MiB` |
| `DASHBOARD_DATA_DIR` | 仅 setup 使用，密钥和快照所在目录，默认 `~/.local/share/mulitca-cost-dashboard` |

`collect` 支持 `--days`、`--dashboard-url`、`--secret-file`、`--snapshot-path`。
同名命令行参数优先于环境变量。`npm run collect -- --help` 查看用法。
退出码 0 表示采集和提交成功，1 表示部分采集失败或执行失败。
大快照自动分块，遇到 HTTP 413 或连接提前重置时有界缩小分块，最低 256 KiB。
达到下限仍失败时，检查大盘、网络及代理请求大小限制，恢复后重跑采集。

管理员密码用于页面读取和价格修改，采集密钥仅用于签名上传。
修改 `PORT` 后同时更新 `COST_DASHBOARD_URL`。
PostgreSQL 服务及数据使用独立的 Compose volume `database`。

## 服务器访问与调度

本机浏览器直连默认回环地址。服务器可使用 SSH 隧道

```bash
ssh -L 4318:127.0.0.1:4318 user@your-server
```

随后打开本机 `http://127.0.0.1:4318`。共享访问时配置 HTTPS 反向代理，
保留原始 Host，转发 Authorization 头。根据代理连接方式配置 HOST。
远端采集目标要求 HTTPS，回环目标支持 HTTP。

使用系统进程管理器保持 `npm start` 运行。需要定时采集时，先验证一次手动采集，
再在运行 Multica 的同一系统账号下设置每日任务。例如 cron

```cron
0 3 * * * cd /absolute/path/mulitca-cost-dashboard && /absolute/path/to/npm run collect -- --days 2 >> /absolute/path/collect.log 2>&1
```

cron 的 PATH 需要包含 Node.js 和 Multica CLI。日志与应用配置保存在本机。
一个应用数据库对应一个 Workspace，多 Workspace 使用独立副本和数据库。

## 统计口径

- 费用、Token、趋势与排行使用 Issue 的 per-model Usage，按每条用量发生日筛选和计价。
  缺少模型明细时，Issue 累计用量按最后活跃日归入所选范围并标记为未定价。
  只有 Issue 数据缺失时才用 Task 补齐。
- Runtime 日用量是独立对账总账，与 Issue/Task 的时间口径不同。
  Runtime 对账覆盖率可能超过 100%。多维排行按 Issue/Task 归因。
- 支持输入、输出、缓存读和缓存写。未定价 Token 可见，预估费用只累加已定价部分。
- 价格按生效日期匹配。支持模型规范化、明确的已知别名及最长已知 custom 模型后缀。
  多个候选价格冲突时，该用量保留为未定价。
- 采集覆盖当前 Workspace 全部项目，并查询离线 Runtime 的历史用量。
  V2 仅替换成功 Runtime 和明确日期窗口内的行。源失败范围保留历史数据。
- Multica 服务端的“今天”时区尚缺明确契约。采集器沿用 UTC 与北京时间窗口的交集，
  跨越两者日期边界时终止并提示重试。365 天回填也遵循该保守窗口。
- 部分 Multica 版本缺少 Task 用量或发起人信息时，页面保留未归属数据。
  成员姓名来自本次采集中的归因记录。

## 排障与验证

| 现象 | 处理 |
| --- | --- |
| 启动失败 | 检查 Node.js 版本、`.env`、密钥权限、数据库连接和迁移状态 |
| 页面暂无数据 | 先运行采集并确认 committed 回执，再选择有数据的日期 |
| 上传 401 | 核对两端采集密钥和机器时间，重跑采集 |
| Multica 403 | 检查目标 profile 的 Workspace Usage 权限 |
| 上传 413 | 增大服务端与采集端 `MAX_PAYLOAD_BYTES`，并核对反向代理大小限制 |
| 来源部分失败 | 在同一账号下检查对应 Multica 命令，修复后重跑 |
| 端口占用 | 修改 PORT 和 COST_DASHBOARD_URL，重启服务 |
| 费用为零 | 检查未定价 Token，并维护相应模型价格 |

```bash
npm test
npm run build
```

隔离数据库集成验证会创建并清理随机测试 schema。使用专用测试数据库执行

```bash
TEST_DATABASE_URL=postgresql://user:password@127.0.0.1/test_database npm run test:integration
```

实现见 [test/integration.mjs](assets/dashboard/test/integration.mjs)。

此开源副本提取已有费用模块和维护中的 Workspace Usage 1.4.0 采集逻辑，
新增自托管启动、身份和配置。发布验证记录见 [VALIDATION.md](VALIDATION.md)。
版本记录见 [CHANGELOG.md](CHANGELOG.md)。

MIT © 2026 Evan Song。见 [LICENSE](LICENSE)。

# 发布验证

## v1.0.1 — 2026-11-13

根据独立验证反馈复用并复核五项修复。补丁基于 v1.0.0，导入前 SHA-256
与验证报告一致。本轮使用新的隔离 PostgreSQL 集群和合成数据重新执行回归。

| 检查 | 结果 |
| --- | --- |
| 安装锁文件依赖、后端与前端类型检查、生产构建 | 通过 |
| 单元测试 | 28 项通过，含 CLI 启动提示和页面网络提示回归 |
| PostgreSQL 集成检查 | 13 项通过，含总测试及 12 个子测试 |
| 独立验证补充脚本 | 19 项通过，含总测试及 18 个子测试 |
| 较旧 V1 上传覆盖保护 | HTTP 409，已提交的较新数据保留 |
| HTTP 413 自动缩块 | 400 KiB 服务限制下缩至 256 KiB，300 行分 5 块提交 |
| 提前断连恢复 | 强制前两次连接重置后缩块提交，300 行唯一数据 |
| npm 运行依赖和全依赖漏洞扫描 | 均为 0 项漏洞 |

补充脚本来自独立验证材料，仅适配当前源码导入路径和隔离测试数据库后执行。
本轮运行环境为 macOS ARM64、Node.js 24.19.0、npm 11.17.0、PostgreSQL 17.10。

### UGLIC 复核

| 维度 | 复核位置与依据 | 结果 |
| --- | --- | --- |
| U 可用性 | scripts/multica-client.mjs:150、web/src/api/client.ts:40 提供恢复提示，新增单元测试通过 | 通过 |
| G 语法 | TypeScript、ESM、package.json 与锁文件，版本统一为 1.0.1 | 通过 |
| L 逻辑 | scripts/collect.mjs:20–58、scripts/usage-v2-protocol.mjs:66 缩块有下限，重试保持 snapshotId | 通过 |
| I 完整性 | src/expenses/service.ts:540、src/expenses/routes.ts:158 在事务锁内拒绝较旧 V1 并返回 409，集成检查通过 | 通过 |
| C 范围与安全 | 修改限于开源包和套件目录版本，发布文件经过内部信息与凭据扫描 | 通过 |

上表文件位置均相对 assets/dashboard。当前未解决的 ERR 和 WARN 均为 0。

### 发布审计

skill-release-audit 按 GitHub 目标执行，六个模块通过，ERR 为 0，WARN 为 0。
保留 frontmatter version 的 INFO，版本已在正文和应用清单中声明。

### 业务核验范围

独立验证报告已确认此前修复代码在 macOS 上的真实 Workspace Token 链路。
本轮发布回归使用合成数据。真实模型费用仍待用户确认模型单价、币种、生效日期和汇率。
真实 Task 用量来源、Docker Compose、Linux/WSL2、远端代理及原生登录框的待验证范围沿用独立报告。

## v1.0.0 — 2026-11-12

验证日期为 2026-11-12。环境为 macOS ARM64、Node.js 24.19.0、npm 11.17.0、
PostgreSQL 17.10 和 Chromium。使用隔离数据库与合成数据。

### 执行结果

| 检查 | 结果 |
| --- | --- |
| 新目录 `npm ci`、setup、build | 通过 |
| TypeScript 后端与前端检查、Vite 生产构建 | 通过 |
| 模型 custom 后缀、价格版本、汇率单元测试 | 26 项通过 |
| PostgreSQL 集成检查 | 10 项通过，包含总测试及 9 个子测试 |
| 并发重复迁移 | 通过，迁移校验和与事务锁正常 |
| 签名上传、重复提交、防重放 | 通过 |
| 分块乱序、失败 Runtime 保留、零用量窗口替换、旧快照拒绝 | 通过 |
| Issue/Task 去重、未定价提示、价格保存后重算 | 通过 |
| Issue runs 查询失败时跳过该 Issue 的覆盖 | 通过，原有模型明细保留 |
| 空数据、浏览器价格新增、合成数据费用展示 | 通过，150 万 Token 按样例价格显示 USD 4.00 |
| 深色主题、项目维度切换 | 通过 |
| 390 × 844 手机视口 | 通过，页面宽度与滚动宽度均为 390 |
| npm 全依赖及运行依赖漏洞扫描 | 0 项漏洞 |
| 内部关键词与凭据字面扫描 | 0 项命中 |
| Skill frontmatter 基础验证 | 通过 |

Multica CLI 命令参数通过本机帮助核对。集成检查通过合成 CLI 响应验证采集器，
随后使用真实 HTTP 请求和 PostgreSQL 验证上传、存储及查询。
真实 Workspace 实采、其他 Multica 版本、Docker Compose 启动、Linux/WSL2
及远端 HTTPS 代理仍需在目标环境验证。

### UGLIC 检查

| 维度 | 核验范围 | 结果 |
| --- | --- | --- |
| U 可用性 | README 安装路径、依赖、登录、配置、失败恢复，页面空状态与手机布局 | 通过 |
| G 语法 | TypeScript、ESM、JSON 锁文件、YAML frontmatter、SQL 迁移 | 通过 |
| L 逻辑 | `assets/dashboard/src/expenses/service.ts` 的计价及去重，V2 分块与范围替换 | 通过 |
| I 完整性 | `assets/dashboard/src/db/migrate.ts` 的空库和重复迁移，采集入口与说明一致性 | 通过 |
| C 范围与安全 | `assets/dashboard/src/app.ts` 的鉴权和静态路径，密钥权限、nonce、跨来源写入、公开文件扫描 | 通过 |

本轮修复了安装输出的构建顺序、通用环境的历史日期边界、依赖漏洞、
默认 CLI profile、示例价格和内部人员映射，并完成相关复核。
当前未解决的 ERR 和 WARN 均为 0。

### skill-release-audit

GitHub 目标的六个模块通过，ERR 为 0，WARN 为 0。
保留一条 INFO，检查器提示 frontmatter 缺少 version。
该套件使用 `name` 和 `description` 两字段格式，版本已写入 SKILL.md 正文和 package.json。

`check_frontmatter.py` 另有四条 ClawHub 卡片格式提示，要求正文标签后使用固定冒号。
本次 GitHub 文档的版本、许可、作者和仓库均已完整展示，保留当前正文格式。

README 与 CHANGELOG 随 GitHub 安装和版本交付提供。

# v1.0.0 发布验证

验证日期为 2026-11-12。环境为 macOS ARM64、Node.js 24.19.0、npm 11.17.0、
PostgreSQL 17.10 和 Chromium。使用隔离数据库与合成数据。

## 执行结果

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

## UGLIC 检查

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

## skill-release-audit

GitHub 目标的六个模块通过，ERR 为 0，WARN 为 0。
保留一条 INFO，检查器提示 frontmatter 缺少 version。
该套件使用 `name` 和 `description` 两字段格式，版本已写入 SKILL.md 正文和 package.json。

`check_frontmatter.py` 另有四条 ClawHub 卡片格式提示，要求正文标签后使用固定冒号。
本次 GitHub 文档的版本、许可、作者和仓库均已完整展示，保留当前正文格式。

README 与 CHANGELOG 随 GitHub 安装和版本交付提供。

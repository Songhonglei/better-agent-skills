# 可选监控板块与高级 Studio

当用户要求“激活监控板块”“Web 看板”“高级 Studio”或同义的 OpenViking 可视化运维时，启用本组件。普通安装、初始化、项目接入与同步不安装、不启动看板，也不改动原版 Studio 入口。用户已要求启用时，在现有授权内完成安装与启动，不再重复询问是否安装。

## 启用

先复用本 Skill 已管理的状态目录、OpenViking 0.5.0 venv、服务地址和项目注册表。脚本中的 `<skill>` 用实际安装目录替换；`--home` 必须与现有部署一致，不为看板重建服务或复制数据库。尚无运行时则按 onboarding 完成初始化。

```sh
python3 <skill>/scripts/ovk.py --home <state> studio install --dry-run
python3 <skill>/scripts/ovk.py --home <state> studio install
python3 <skill>/scripts/ovk.py --home <state> studio start
python3 <skill>/scripts/ovk.py --home <state> studio status
```

默认地址 `http://127.0.0.1:1934/`。端口被占用时先辨认现有实例，或首次安装用 `studio install --port 21934` 选择空闲端口。看板只绑定 loopback，不额外安装第三方依赖或启动模型服务；它检查现有 venv 中的 FastAPI、httpx、uvicorn、Pydantic 2 和 OpenViking 0.5.0。缺依赖时先诊断现有环境，不自动重装运行时。

代码部署到 `<state>/dashboard/app/`，指纹为 `app-manifest.json`，端口为 `config.json`，PID、日志和入口回执同在 `<state>/dashboard/`。重复安装校验内容；本地改动、不同版本或未管理的目录会保留并报错，不静默覆盖。升级先停看板，保存并审阅旧目录和回执，在隔离目录验证新版本后再替换应用文件；原版入口回执和备份应保留。常规 `install` 不升级这套可选组件。

## 可选替换 Studio 首页

用户要求高级 Studio 替代默认页面或替换首页时，先确认看板已经就绪，然后运行：

```sh
python3 <skill>/scripts/ovk.py --home <state> studio install-entry
```

原服务的 `/studio/home` 会跳转到看板。原版通过看板侧栏或 `/studio/home?view=classic` 访问；原服务地址读取 `configs/service.json`，不假定端口为 1933。`studio-original.html` 和 `studio-entry.json` 保存原文及 SHA-256 回执。

恢复入口与停止看板相互独立。替换过入口时，先恢复再停看板：

```sh
python3 <skill>/scripts/ovk.py --home <state> studio restore-entry
python3 <skill>/scripts/ovk.py --home <state> studio stop
```

恢复前核对安装指纹和备份，不覆盖用户后来编辑的页面。OpenViking 包升级可能改变或移除首页，先检查回执与新包内容。登录自启动和定时任务不随看板启用；需要时单独按用户要求配置。

## 功能与数据含义

- 总览：本机认证、服务就绪、全服务队列、进程内存、磁盘、项目知识新鲜度。
- 项目资料：读取注册表中的任意项目，显示白名单、选区、证据日期、同步回执、MCP 验收和零模型调用的 dry-run。
- 任务：按项目筛选、搜索、游标分页、详情与部分失败提示。
- 模型与用量：现有摘要及 embedding 配置、按北京时间汇总的七天持久 Token 记录、进程内计数。
- 检索：每次三条命中，带快照分页回读；只有检索会调用现有 embedding 服务，实际提供方沿用本机配置。
- 服务事件：隐藏已知凭据后的历史错误与告警，明确为全服务范围。

监控 API 只读，不提供同步写入、删除或任意代理端点。密钥由本机后端读取，不交给浏览器。原文数按白名单，索引原文数含规则，向量条目可含生成摘要；进程计数和持久用量分别展示，不等同于供应商账单。`setup-check` 是初始化验收项目，默认隐藏，可勾选查看。共享账号的项目用量和向量数据来自同一账号，不能当作独立项目隔离统计。

## 启用验收

实际访问页面，检查“本机连接已确认”、项目资料数与本机白名单一致；试一次项目筛选、任务分页和资料预览。用户要求检索验证时做真实 find/read，并区分模型调用与静态检查。历史告警不代表当前故障，以实时 ready 为准；认证或读取失败展示不可用，不把失败当零值。保存本次结果并给出看板地址、启停和恢复命令。

组件回归在现有 venv 中执行，不需要真实模型密钥：

```sh
<state>/venv/bin/python -m unittest discover -s <skill>/assets/dashboard/tests -v
node --check <skill>/assets/dashboard/static/app.js
python3 <skill>/scripts/selftest.py
```

已在 macOS 上验证本机生命周期与桌面、390px 浏览器流程。Linux/WSL2 使用相同运行模块，尚未声称完成这些平台的浏览器和全新安装验收。

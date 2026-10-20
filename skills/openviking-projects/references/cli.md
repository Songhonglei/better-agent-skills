# 命令与参数

入口为 `python3 <skill>/scripts/ovk.py [--home PATH] <命令>`。`--home` 位于命令前，默认取 OVK_HOME，未设置时用 `~/.openviking-projects`；应选 Skill 外专用目录。入口及子命令均支持 `--help`，运行时子命令的帮助需先安装运行时。未知参数会报错，不会静默丢弃。

## 安装入口

| 命令 | 参数与默认行为 |
| --- | --- |
| preflight | 无额外参数；只读显示 Python、平台、Git 和所选状态目录的运行时存在性；不扫描其他安装目录 |
| install | `--index auto`：PyPI→清华→阿里云，或 pypi/tuna/aliyun/HTTPS Simple URL；`--wheelhouse PATH` 指定完整离线目录并优先于 index；`--python PATH` 选择创建 venv 的 Python 3.11+，默认当前 Python；`--dry-run` 只显示命令计划 |
| configure | `--models PATH` 必填，模型参数 JSON；`--secrets PATH` 可选本机密钥 JSON，不提供时使用参数中指定的环境变量；`--port 1933`，范围 1024–65535，只绑定 loopback；拒绝覆盖已有配置 |
| fetch-source | `--url HTTPS_URL`、`--commit FULL_40_LOWERCASE_HEX`、`--destination PATH` 均必填；仅获取固定源码，不构建；目标必须不存在 |

安装需先用 Python 3.11+ 启动本工具，即使指定了另一个 --python。日志位于状态目录 `logs/install-*.log`，完成/失败回执为 `evidence/install-last.json`。来源、离线 tokenizer 和 TLS 说明见 [network-install.md](network-install.md)。

## 运行时入口

| 命令 | 参数与默认行为 |
| --- | --- |
| doctor | `--probe-models` 分别实际调用摘要和 embedding；省略时执行服务官方 doctor。探针结果写 evidence/model-probe.json，验收以本次退出状态为准 |
| start / stop / status | 无额外参数；start 等待 ready，stop 只发 SIGTERM 给自有 PID；status 返回 ready 和项目列表，不会启动服务 |
| project add CODE | `--workspace PATH`、`--policy PATH` 必填；`--identity isolated` 默认项目独立账号，shared 是显式共享账号；`--dry-run` 校验策略并预览，不建账号/项目状态；CODE 为 1–48 位小写字母、数字或连字符，首位非连字符 |
| project sync CODE | `--dry-run` 显示变化，不调用模型；省略时同步该项目，增量每轮最多 5 份变更 |
| project alias CODE | `--workspace PATH` 必填，登记额外 clone 路径；复用主资料索引，不会同步这个分支 |
| sync-all | 只同步已启用定时列表；`--scheduled` 是时钟任务入口，只在配置的工作日和分钟、当日未尝试时运行；手动诊断通常省略 |
| mcp | 默认预览全局 openviking；`--apply` 才写配置；`--config-file PATH` 指定其他目标；兼容参数 `--workspace PATH` 只校验目录；不覆盖另一套同名部署 |
| autostart | 默认生成登录启动内容；`--apply` 安装并加载系统任务，需要用户授权；现有任务拒绝覆盖 |
| schedule | `--enable CODE` / `--disable CODE` 可重复；`--at 12:30`、`--timezone Asia/Shanghai`；默认预览，`--apply` 保存列表并确保时钟任务存在；enable 要求当前快照已 verify |
| verify CODE | `--query TEXT` 必填；`--contains FACT` 可重复，要求检索回读包含全部事实，不提供时只验证可用性；写项目 evidence/mcp-check.json |

裸命令 `serve` 仅用于生成的系统服务，执行同一自有 OpenViking 进程，不提供单独业务入口。底层 `prepare_sources.py --dry-run` / `import_sources.py --dry-run` 用于诊断；`import_sources.py --migrate-layout` 仅在明确审阅旧 schema-1 布局迁移时使用，不作为超限重试方法。

## 状态、退出与恢复

- 0：操作完成或预览成功；重复配置可返回 already_configured。status 的 0 代表读取状态成功，应另外检查 ready。时钟未到期可无输出退出。
- 1：已知操作失败；同步 complete/unchanged 才成功，failed/partial 需逐项检查，skipped/already_running 等待原进程，不追加重试。
- 2：参数解析失败。透传的子命令沿用其非零失败码，不能把其他非零值当成功。
- 安装失败看 logs/install-*.log；服务未 ready 看 logs/server.log；同步失败看项目 logs/scheduled-sync.log 和 evidence/sync-journal.json。提交结果未知先查已有任务，不盲目重提。
- 已有运行时指纹不同会拒绝覆盖；先保存配置/凭据和数据，审阅升级差异并用隔离目录验证。新 Skill 包不会自动替换已安装服务，更不会改装旧试点。

## 自检入口

`python3 <skill>/scripts/selftest.py [--native-python PATH] [--report PATH]`：默认只跑标准库离线检查，--native-python 明确复用已有 OpenViking 0.5.0 依赖，--report 保存结果。OVK_TEST_TOKENIZER_CACHE 是可选公开编码表缓存；不设置时下载到测试临时目录。详见 [validation.md](validation.md)。

全局 MCP 配置目录可由 Codex 的 CODEX_HOME 选择；项目路由由每次调用的 project_code/workspace_path 决定。OVK_PROJECT 仅由内部项目子进程使用，不应作为会话级“当前项目”开关。

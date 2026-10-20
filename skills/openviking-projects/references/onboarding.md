# 新电脑接入

## 环境选择

先运行 `python3 <skill>/scripts/ovk.py preflight`。所有 `<skill>` 均替换为实际 Skill 目录；不要把示例路径原样执行。命令支持前置 `--home /专用状态目录`。已有服务就先核对配置和管理入口，不能用这个新运行时覆盖其他安装。

准备 Python 3.11+ 和 venv。macOS Apple Silicon 的 OpenViking 0.5.0 wheel 要求 macOS 14+，Intel wheel 要求 macOS 15+；Linux wheel 对应 glibc 2.31+ 的 x86_64/aarch64。其他系统或 CPU 先检查 wheel，不把编译依赖当作默认前置。Windows 用户可在 WSL2 中使用完整附加运行时；原生 Windows 安装服务见官方文档，但本包的 fcntl 和系统任务不可直接使用。

## 安装与配置

```sh
python3 <skill>/scripts/ovk.py install --dry-run
python3 <skill>/scripts/ovk.py install --index auto
```

auto 按 PyPI → 清华 → 阿里云顺序有界尝试；离线、源码镜像和 Docker 替代路径读 network-install.md。不会执行远程 shell 或修改全局 pip 源。venv 与状态在 Skill 之外。

在本机准备模型参数 JSON，例如下面的结构。地址和模型必须由用户或其已有服务确定；这不是可直接使用的服务配置。

```json
{
  "embedding": {
    "provider": "openai",
    "api_base": "https://model-gateway.example.org/v1",
    "model": "chosen-embedding-model",
    "api_key_env": "OVK_EMBEDDING_KEY",
    "options": {"dimension":4096,"encoding_format":"float","batch_size":8}
  },
  "vlm": {
    "provider": "openai",
    "api_base": "https://model-gateway.example.org/v1",
    "model": "chosen-summary-model",
    "api_key_env": "OVK_SUMMARY_KEY",
    "options": {"max_tokens":2048,"max_concurrent":2,"max_retries":1,"timeout":60}
  }
}
```

4096 只是结构示例，必须替换为模型实际维度。摘要与 embedding 可以用不同网关和不同 key。Ollama 使用 provider=ollama、本机 origin，按已确认模型填写，省略 api_key_env；小型模型的摘要质量仍要实测。Azure 等提供商配置与最小探针不完整覆盖时，使用官方初始化/doctor 并按真实 provider 调整，不假装 OpenAI 兼容。

密钥通过用户本机的 0600 JSON 文件交付，字段是选定的 `api_key_env` 变量名；或者预先设置这些环境变量。不要把真实值放进文档、终端命令参数或聊天。

```sh
python3 <skill>/scripts/ovk.py configure --models /local/models.json --secrets /local/provider-keys.json
python3 <skill>/scripts/ovk.py doctor --probe-models
python3 <skill>/scripts/ovk.py doctor
python3 <skill>/scripts/ovk.py start
```

configure 只在新配置目录使用，拒绝覆盖现有配置；新建本机 root key，服务仅监听 127.0.0.1。密钥保存在私有状态目录，不写进 MCP 配置。服务端配置使用环境变量引用，后台和登录启动同样可读取本机选定凭据。

最小探针分别调用两个模型；403 常见于 key 未绑定 embedding；返回向量长度必须与索引维度一致。维度/模型变化涉及既有向量库时用新实例或显式重建，不直接改配置继续使用旧向量。

## 接入项目

先完成资料整理与 policy，见 project-policy.md。

```sh
python3 <skill>/scripts/ovk.py project add demo --workspace /local/project --policy /local/policy.json --dry-run
python3 <skill>/scripts/ovk.py project add demo --workspace /local/project --policy /local/policy.json
python3 <skill>/scripts/ovk.py project sync demo --dry-run
python3 <skill>/scripts/ovk.py project sync demo
python3 <skill>/scripts/ovk.py mcp
python3 <skill>/scripts/ovk.py mcp --apply
python3 <skill>/scripts/ovk.py verify demo --query '当前入口和状态依据是什么' --contains '项目中应找到的事实'
```

默认独立账号，共用一个全局 `openviking` MCP；共用 MCP 不代表共用后端账号。mcp 默认只预览，--apply 才写入 `${CODEX_HOME:-~/.codex}/config.toml` 的 `[mcp_servers.openviking]`，保留其他表并备份旧文件，不自动改变 Codex 信任设置。只需注册一次，后续项目省略这两条 mcp 命令；同一配置重复执行返回 already_configured。已有同名 MCP 指向其他运行时则拒绝覆盖，应复用已有部署。每次调用仍必须带 project_code 和绝对 workspace_path。Codex 新会话重新加载后再实测一次 find/read，不把 CLI 配置可见当成原生会话验证。

从 1.0.0 升级时先检查全局及各工作区 `.codex/config.toml` 中的 `openviking_projects` 旧注册，确认迁移目标后再移除旧条目，避免同时加载两套 MCP；本工具不会自动删改已有部署。`--config-file /local/codex/config.toml` 可显式选择其他客户端配置；兼容参数 `--workspace` 只检查目录，不再决定配置写入位置。

凭据未知结果、已有账号但本地 key 丢失时停止并恢复 key，不重新创建或轮换碰运气。该流程不复制原电脑项目内容；将项目文档通过正常受控版本管理送到新电脑，再在新路径注册并索引。

官方依据：[服务安装](https://docs.openviking.ai/en/getting-started/04-setup-for-agent)、[0.5.0 发行元数据](https://pypi.org/pypi/openviking/0.5.0/json)。

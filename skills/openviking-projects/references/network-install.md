# 网络受限安装

## 首选：不用 GitHub 的预编译包

```sh
python3 <skill>/scripts/ovk.py install --index tuna --dry-run
python3 <skill>/scripts/ovk.py install --index tuna
```

可选 pypi、tuna、aliyun、auto，或用户指定的 HTTPS Simple API URL。每次只使用一个 index-url，不混用 extra-index-url；不关闭 TLS 校验，不自动修改全局代理、git 或 pip 配置。镜像落后、没有当前平台的 0.5.0 wheel 时停止，保留安装日志，改选另一个来源。默认要求全部依赖使用 wheel；缺少任何必需 wheel 时停止，不静默转入源码编译。用户明确选择源码路径后再处理编译依赖。

安装子进程忽略已有 pip 配置及会改变来源/安装位置的 `PIP_*` 环境变量，避免 PIP_TARGET 等把依赖安装到 venv 外。保留 `PIP_CERT`、`PIP_CLIENT_CERT` 与系统代理/证书环境以支持公司网络；不关闭 TLS。

原理：安装 PyPI 分发的 OpenViking 0.5.0 wheel，不需要 git clone GitHub。安装后核对版本、原生模块与打包的 CLI/AGFS 组件，再做真实导入。不能仅凭 pip 退出码断言原生依赖可用。

来源：[清华 PyPI 镜像说明](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/)、[OpenViking PyPI](https://pypi.org/project/openviking/0.5.0/)。

## 离线 wheelhouse

在可联网且与目标 OS/CPU/Python ABI 匹配的环境准备完整依赖包：

```sh
python3 -m pip download --prefer-binary --only-binary=:all: --dest /local/wheelhouse --index-url https://pypi.tuna.tsinghua.edu.cn/simple 'openviking==0.5.0' 'mcp>=1.27,<2' 'tiktoken>=0.9,<1'
python3 <skill>/scripts/ovk.py install --wheelhouse /local/wheelhouse --dry-run
python3 <skill>/scripts/ovk.py install --wheelhouse /local/wheelhouse
```

确认 wheelhouse 来自可信来源，并随包保存来源与 SHA256 清单。不要把 macOS wheelhouse 宣称为 Linux 通用；不要把虚拟环境目录直接拷贝跨机器使用。

tiktoken 首次加载 o200k_base 另需公开编码表，不包含在 wheelhouse 中。联网环境用 `TIKTOKEN_CACHE_DIR=/local/tokenizer-cache python3 -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'` 加载，再把这个公开 cache 目录的内容复制到目标状态目录的 cache/tiktoken；库会核验编码表指纹。此目录不得混入原项目 manifest、凭据或私有数据。离线系统缺失时区数据时也要准备 tzdata/系统时区文件。离线验收必须实际启动 MCP，不只安装 Python 包。模型网关仍须可达；若完全离线，需事先准备可用本地模型及其权重，不把 wheelhouse 当作模型包。

## 官方国内容器替代

若用户选择 Docker，可用 `ghcr.io/volcengine/openviking`；GitHub Container Registry 不通时，官方文档给出 `openviking-cn-beijing.cr.volces.com/volcengine/openviking`。先查明 0.5.0 对应可用 tag 或 digest，锁定后 pull；不能编造 tag，也不要让 nightly/latest 无声替换已验证版本。

持久化配置和数据，端口只绑定 127.0.0.1。容器 server 与本包宿主机管理脚本是两种部署方式：本包 start/stop/autostart 面向原生 venv；若改用容器，要调整运维入口并验证宿主 CLI 上传和路径映射，不能直接把宿主绝对路径当成容器路径。

来源：[官方安装的 Docker 替代 registry](https://docs.openviking.ai/en/getting-started/04-setup-for-agent)。

## 用户指定源码镜像

确实需要源码或平台没有 wheel 时，允许公司 GitLab、企业镜像等明确可信 HTTPS 仓库，不默认把凭据交给未知公共 GitHub 代理。先从可信上游确认完整 commit：

```sh
python3 <skill>/scripts/ovk.py fetch-source --url https://trusted-mirror.example.org/volcengine/OpenViking.git --commit FULL_40_HEX_COMMIT --destination /local/openviking-source
```

工具只在新目录获取并核对 commit，不执行源码。commit 不匹配、历史不全或镜像无法提供该对象就失败，不回退分支。然后按该 commit 的构建文档准备 Rust/C++/CMake 等，检查构建产物版本，并验证本包 HTTP/目录语义。源码镜像不是 wheel 镜像；git 成功不代表构建时所有依赖能联网。

不要自动改写所有 github.com URL，不执行下载后未经查看的安装 shell。若分发本 Skill 的 GitHub 仓库也不可达，可以直接传递干净 ZIP/.skill 包，不需要访问任何 GitHub URL。

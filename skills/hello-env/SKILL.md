---
name: hello-env
description: "Universal dev-environment health check for Linux/macOS hosts, containers, and K8s pods. Pure bash, zero dependencies. Reports OS, current user, Node.js (path + version), Python3, basic tools (git/curl/jq/docker), network (hostname/IP/inferred private subnet), container/K8s detection (configurable env-var probe; defaults to KUBERNETES_SERVICE_HOST + K8S_NAMESPACE), workdir & git status, optional config-file check, and PVC remount detection (device-number + watch-dir count snapshot diff to detect K8s PersistentVolume reattach silently rotating to a fresh disk). Three layers of config: CLI flags > env vars > sensible defaults. Trigger when user says any of: 'check my env', 'environment check', 'hello-env', 'system info', 'is my environment ok', 'what's my IP', 'what env am I in', 'has my PVC been remounted', 'detect K8s pod', 'basic tools check', 'node version', 'who am I' — or 「检查我的环境」「环境自检」「hello-env」「查看系统信息」「环境有没有问题」「IP 是多少」「在什么环境」「PVC 换卷了吗」「基础工具检查」「node 版本」「当前用户是谁」 — or any phrasing expressing the intent to verify a dev environment is healthy / detect container/K8s context / catch silent PVC rotation."
license: MIT
metadata:
  author: Evan Song
  version: "1.0.1"
---

# hello-env

> A zero-dependency Bash health check for any dev environment — host, container, or K8s pod.
>
> 一个零依赖的开源环境自检脚本，适用于本地、容器、K8s Pod 环境。

Pure `bash`. No Python, no npm, no third-party packages. Works on macOS, Linux, and inside containers.

- **Author**: Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)
- **Repository**: https://github.com/Songhonglei/better-agent-skills
- **License**: MIT

## Compatibility

| Platform | Status |
|---|---|
| Linux (any distro) | ✅ Full |
| macOS (bash 3.2.57+ default) | ✅ Full — uses `eval`-based indirect var expansion for bash 3.x |
| Windows (WSL / WSL2) | ✅ Full (effectively Linux) |
| Windows (Git Bash / MSYS / Cygwin) | ⚠️ Partial — OS/user/tools/network checks work; cgroup container detection and PVC monitoring are skipped (Linux-only kernel features) |
| Windows (PowerShell / cmd) | ❌ Not supported by design (bash script) |

| Agent Platform | Status |
|---|---|
| Claude Code | ✅ Standard SKILL.md, drops in |
| Codex | ✅ Same |
| OpenClaw | ✅ Native format |
| Cursor / Cline / others | ✅ Generic Markdown + bash, no platform hooks |

---

## Quick start

```bash
# Run with defaults (current directory as workdir, default K8s probe vars)
bash scripts/check-env.sh

# Custom workdir
bash scripts/check-env.sh --workdir /opt/myapp

# Probe extra environment variables (comma-separated)
bash scripts/check-env.sh --probe-env "MY_REGION,MY_TIER,DEPLOY_ENV"

# Force PVC monitoring (when K8s probe vars are absent but you still want it)
bash scripts/check-env.sh --force-pvc

# Combine
bash scripts/check-env.sh \
  --workdir /opt/myapp \
  --watch-dir /opt/myapp/plugins \
  --config /etc/myapp/config.json \
  --probe-env "MY_REGION,MY_TIER" \
  --force-pvc
```

---

## What it checks

| # | Module | Output |
|---|---|---|
| 1 | OS | macOS / Linux distro + version |
| 2 | Current User | `whoami` + UID/GID |
| 3 | Node.js | Path (`which node`) + version |
| 4 | Python3 | Path + version |
| 5 | Basic Tools | git, curl, jq, docker, make — present / missing |
| 6 | Network | Hostname + IP + inferred private subnet (10.x / 172.16-31.x / 192.168.x) |
| 7 | Container / K8s | Probes configurable env vars; defaults to `KUBERNETES_SERVICE_HOST` + `K8S_NAMESPACE`; falls back to `/.dockerenv` / cgroup heuristics |
| 8 | Workdir | Path exists + git initialized check |
| 9 | Config file | Only checked if `--config <path>` provided |
| 10 | PVC persistence | Mount device-number + watch-dir count snapshot diff (auto when K8s probe hits, or `--force-pvc`) |

Output legend: ✅ ok · ℹ️ info · ⚠️ warning · ❌ failure

---

## CLI flags

| Flag | Default | Description |
|---|---|---|
| `--workdir <path>` | `pwd` | Working directory to check (existence + git init) |
| `--watch-dir <path>` | `<workdir>` | Directory whose subfolder count is snapshotted for PVC monitoring |
| `--config <path>` | _(unset)_ | Optional config file to check existence |
| `--probe-env "A,B,C"` | `KUBERNETES_SERVICE_HOST,K8S_NAMESPACE` | Comma-separated env vars to probe for container/K8s context |
| `--force-pvc` | off | Force PVC monitoring even when no K8s indicator is found |
| `--snapshot-dir <path>` | `<workdir>/.hello-env` | Where to store device/count snapshots |
| `-h, --help` | — | Show inline help |

---

## Environment variables (lower priority than CLI flags)

| Variable | Equivalent flag |
|---|---|
| `HELLO_ENV_WORKDIR` | `--workdir` |
| `HELLO_ENV_WATCH_DIR` | `--watch-dir` |
| `HELLO_ENV_CONFIG` | `--config` |
| `HELLO_ENV_PROBE_ENV` | `--probe-env` |
| `HELLO_ENV_FORCE_PVC=1` | `--force-pvc` |
| `HELLO_ENV_SNAPSHOT_DIR` | `--snapshot-dir` |

---

## PVC remount detection (why this matters)

K8s PersistentVolumes can silently get **reattached to a fresh disk** during pod restarts or node failover. Symptoms users typically see:

> "All the files I created yesterday are gone after the pod restarted."

This script catches it early by snapshotting on each run:

- `<snapshot-dir>/last-device` — the mount device for `<workdir>`
- `<snapshot-dir>/last-watch-count` — `find <watch-dir> -maxdepth 1 -mindepth 1 -type d | wc -l`

Next run decides:

| Device | Watch-dir count | Verdict |
|---|---|---|
| changed | any | ⚠️ Likely PVC remount |
| unchanged | decreased | ℹ️ Probably manual removal |
| unchanged | not decreased | ✅ Healthy |

**When PVC monitoring activates:**
- Any of the env vars listed in `--probe-env` is set, OR
- `--force-pvc` / `HELLO_ENV_FORCE_PVC=1` is on

If neither, you get a hint:

> ℹ️ Not detected as containerized environment. Use `--force-pvc` to enable PVC monitoring anyway.

---

## Examples

### CI runner sanity check

```bash
bash scripts/check-env.sh --workdir "$CI_PROJECT_DIR" --probe-env "CI,GITLAB_CI,GITHUB_ACTIONS"
```

### K8s pod with custom labels

```bash
bash scripts/check-env.sh \
  --probe-env "KUBERNETES_SERVICE_HOST,K8S_NAMESPACE,MY_REGION,MY_TIER" \
  --watch-dir /workspace/plugins
```

### Local Docker container without K8s

```bash
bash scripts/check-env.sh --force-pvc --workdir /app
```

---

## Exit codes

- `0` — All checks ran (warnings allowed)
- Non-zero only on argument parsing errors

This is a **diagnostic** tool, not a gate. It reports — it doesn't block.

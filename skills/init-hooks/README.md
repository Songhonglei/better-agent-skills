# init-hooks

> Run scripts automatically every time your OpenClaw agent's container/host boots — survives gateway restarts, container restarts, and container rebuilds. Registry-driven, idempotent, with inline / local-script / remote-CDN hook types.

`init-hooks` solves a common pain point for containerized AI agents: **initialization logic gets lost on container rebuild**. It keeps a persistent hook registry inside your workspace and re-runs your startup hooks on every boot.

## Features

- **Three hook types**
  - `inline` — a few shell commands, no file needed
  - `script` / `python` — a local `.sh` / `.py` file
  - `CDN URL` — a `zip` / `tar.gz` fetched & extracted on first run (auto re-download after container rebuild)
- **Survives rebuilds** — registry + logs live in `workspace/.init-hooks/` (mount your workspace on a persistent volume and hooks persist forever)
- **Idempotent install** — safe to re-run; auto-injects into `post-init.sh` and (optionally) the container start script
- **Lenient execution** — one failing hook never blocks the rest; every run is logged with a success/failure summary
- **Ordered execution** — control run order with `--order`
- **Full CRUD** — add / list / show / edit / enable / disable / delete / run / status
- **Config sync helper** — `sync_openclaw_config.py` keeps `openclaw.json` mirrored to extra persistence paths (configurable, see below)
- **Portable** — no hardcoded absolute paths; uses `$HOME` / `Path.home()` throughout

## Quick Start

```bash
# Clone (or install via clawhub / skills.sh)
git clone https://github.com/Songhonglei/better-agent-skills.git

# Point SCRIPT at wherever the skill landed in your agent, e.g.
#   OpenClaw:     ~/.openclaw/workspace/skills/init-hooks
#   Claude Code:  ~/.claude/skills/init-hooks
#   Cursor:       .cursor/skills/init-hooks
SCRIPT="/path/to/init-hooks/scripts/manage.py"

# 1. Install (idempotent)
python3 $SCRIPT install

# 2. Add a startup hook
python3 $SCRIPT add \
  --name "boot marker" \
  --type inline \
  --content 'echo "[boot] $(date)" >> "$HOME/.openclaw/workspace/.init-hooks/boot.log"'

# 3. Test it immediately
python3 $SCRIPT run

# 4. See what's registered
python3 $SCRIPT list
```

## Environment variables (deployment-specific)

Different deployments persist config in different places. These are optional:

| Variable | Purpose | Default |
|---|---|---|
| `INIT_HOOKS_SYNC_PATHS` | Extra `openclaw.json` mirror targets for `sync_openclaw_config.py` (colon-separated; missing paths skipped). Leave empty on plain local setups. | *(empty)* |
| `INIT_HOOKS_START_SH` | Container start-script path to inject the dispatcher into | `/app/start.sh` |

Example for a K8s / container deployment (replace with your own mount layout):

```bash
export INIT_HOOKS_SYNC_PATHS="/app/clawconfig/openclaw.json:/app/k8s-config/clawconfig/openclaw.json"
```

## Usage

Full command reference and hook-authoring best practices live in
[SKILL.md](./SKILL.md) and [references/best-practices.md](./references/best-practices.md).

## Install in your AI agent

| Agent | Install |
|---|---|
| OpenClaw | `clawhub install init-hooks` |
| Claude Code | Manual: copy to `~/.claude/skills/` |
| Cursor | Manual: copy to `.cursor/skills/` |

## License

MIT (see [LICENSE](./LICENSE))

## Author

Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)

## Changelog

### v1.0.0 (2026-07-13)

- Initial public release
- Registry-driven startup hooks with inline / script / python / CDN-URL types
- Idempotent install, lenient ordered execution, run logging
- `sync_openclaw_config.py` config mirroring, now configurable via `INIT_HOOKS_SYNC_PATHS`
- Container start-script path configurable via `INIT_HOOKS_START_SH`

---
name: claw-memory-manager
description: >
  Manage OpenClaw Agent's built-in memory features — enable/disable/configure
  Dreaming (Light→REM→Deep auto memory consolidation), tune half-life and
  max-age parameters, schedule timezone, and synchronize config across
  managed environments. Auto-detects K8s ConfigMap mirrors, creates backups
  before write, supports dry-run preview, and triggers gateway restart to
  apply changes. Reserved extension point for future active-memory feature.
  适用场景:开启 Dreaming/关闭 Dreaming/配置记忆整合/调整记忆半衰期/管理 agent 内置记忆功能。
---

# Claw Memory Manager

- **Version**: 1.0.0
- **License**: MIT
- **Author**: Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)
- **Repository**: https://github.com/Songhonglei/better-agent-skills

Manage [OpenClaw](https://docs.openclaw.ai) Agent's built-in memory features.
Currently supports **dreaming** (memory consolidation); extensible to
**active-memory** and other future features.

## What it does

OpenClaw Agent has a built-in **Dreaming** mechanism: a scheduled job (default
03:00 local time) that scans your daily memory signals, scores them, and
**auto-promotes high-recall items to long-term `MEMORY.md`**. Enabling/tuning
this requires editing a nested config tree, syncing to multiple paths in
managed environments, and restarting the gateway — this skill does all that
in one command, safely.

## Supported features

| Feature | What | Status |
|---------|------|--------|
| `dreaming` | Light→REM→Deep three-phase memory consolidation | ✅ |
| `active-memory` | Proactive memory injection (extension slot) | 🚧 Reserved |

See `references/features.md` for details on each feature.

## Quick start

```bash
# Check if your OpenClaw version supports dreaming
python3 scripts/agent_memory.py check dreaming

# See current state
python3 scripts/agent_memory.py status dreaming

# Enable with defaults (half-life 30d, max-age 60d, timezone UTC)
python3 scripts/agent_memory.py enable dreaming

# Enable with custom half-life and timezone
python3 scripts/agent_memory.py enable dreaming --half-life 14 --timezone America/New_York

# Preview without writing
python3 scripts/agent_memory.py enable dreaming --dry-run

# Disable
python3 scripts/agent_memory.py disable dreaming
```

## CLI flags

| Flag | Purpose | Default |
|------|---------|---------|
| `--half-life N` | Signal decay half-life (1-90 days) — controls how fast old signals lose weight | `30` |
| `--max-age N` | Signal hard expiry (1-90 days) — older signals are excluded from promotion | `60` |
| `--timezone TZ` | IANA timezone for the dreaming schedule | `UTC` |
| `--dry-run` | Print planned changes without writing | off |
| `--no-backup` | Skip `*.bak.<timestamp>` creation before write | off (backup on) |
| `--no-restart` | Skip `openclaw gateway restart` after change | off (auto-restart on) |

## Safety features

| Layer | Behavior |
|-------|----------|
| **Auto-backup** | Every write creates `openclaw.json.bak.<YYYYMMDD_HHMMSS>` (use `--no-backup` to opt out) |
| **Dry-run** | `--dry-run` prints exact JSON change + sync targets + restart action without touching disk |
| **Managed-env auto-detect** | `/app/clawconfig/` and `/app/k8s-config/clawconfig/` auto-detected — synced if present, silently skipped if not (handles both local & K8s deployments) |
| **Validation** | Half-life and max-age ranges enforced (1-90 days); invalid input exits non-zero |
| **Verify after write** | Re-reads config to confirm change took effect before reporting success |

## Configuration sources

The script reads/writes:

1. **Runtime config**: `~/.openclaw/openclaw.json` (or `$OPENCLAW_CONFIG`)
2. **Managed-environment mirrors** (auto-detected, optional):
   - `/app/clawconfig/openclaw.json` (Pod restart source in K8s)
   - `/app/k8s-config/clawconfig/openclaw.json` (K8s ConfigMap source)

If you run OpenClaw locally (e.g. `npm install -g openclaw` on your laptop),
only the runtime config exists and the script does the right thing
automatically.

## Why use this skill

Without this skill, enabling Dreaming requires:

1. Reading the OpenClaw config schema docs
2. Editing nested JSON under `plugins.entries.memory-core.config.dreaming`
3. Setting `phases.deep.recencyHalfLifeDays` separately
4. Copying to 2 mirror paths (in K8s environments)
5. Running `openclaw gateway restart`
6. Manually verifying

This skill: **one command**, with backup + dry-run + verify built in.

## Extending to new memory features

Add a new entry to the `FEATURES` dict at the top of `agent_memory.py`:

```python
FEATURES["my-feature"] = {
    "path": ["plugins", "entries", "my-plugin", "config"],
    "enable_patch": {"enabled": True, ...},
    "disable_patch": {"enabled": False},
    "check_key": "enabled",
    "status_key": "frequency",  # field shown in `status`
    "description": "What this feature does",
}
```

## Files

```
claw-memory-manager/
├── SKILL.md              ← agent entry point
├── README.md             ← this file
├── LICENSE               ← MIT
├── .gitignore
├── scripts/
│   └── agent_memory.py   ← single Python entry, zero external deps
└── references/
    └── features.md       ← feature catalog + schema reference
```

## See also

- `references/features.md` — full feature catalog, config schemas, and extension guide
- [OpenClaw docs](https://docs.openclaw.ai) — platform reference

# Feature Catalog — OpenClaw Agent Memory Features

This document describes each supported memory feature, its config schema,
recommended settings, and extension instructions.

## Dreaming (memory consolidation)

| Attribute | Value |
|-----------|-------|
| **What** | Light→REM→Deep three-phase auto memory consolidation; promotes high-recall signals to `MEMORY.md` |
| **Min OpenClaw version** | 2026.4.24+ |
| **Config path** | `plugins.entries.memory-core.config.dreaming` |
| **Plugin dependency** | `memory-core` (loaded by default via `plugins.slots.memory: "memory-core"`) |
| **Schema fields** | `enabled` (bool) / `frequency` (cron expr) / `timezone` (string) / `verboseLogging` (bool) / `storage` (obj) / `phases` (obj) |

### Recommended baseline config

```json
{
  "enabled": true,
  "timezone": "UTC",
  "frequency": "0 3 * * *"
}
```

### Promotion parameters (under `phases.deep`)

| Param | Default | Purpose | Tunable via |
|-------|---------|---------|-------------|
| `minScore` | `0.8` | Composite score threshold to qualify | (manual edit) |
| `minRecallCount` | `3` | Minimum times signal was recalled | (manual edit) |
| `minUniqueQueries` | `3` | Minimum distinct query contexts | (manual edit) |
| `recencyHalfLifeDays` | `30` | Signal weight half-life | `--half-life 1-90` |
| `maxAgeDays` | `60` | Hard expiry — older signals excluded | `--max-age 1-90` |
| `limit` | `10` | Max items promoted per run | (manual edit) |

### Verification commands

```bash
openclaw memory status | grep Dreaming
openclaw memory promote          # preview promotion candidates (no write)
openclaw memory promote --apply  # execute promotion immediately
```

### Implementation notes

- `plugins.entries.memory-core.config.dreaming` is **not** in the
  `sync-config-fields.sh` allow-list, so in K8s managed environments it
  still needs to be mirrored to `/app/clawconfig/` and
  `/app/k8s-config/clawconfig/` to survive Pod restarts. This skill does
  that automatically (auto-detected paths; no-op on local installs).
- After config write, a gateway restart picks up changes. This skill runs
  `openclaw gateway restart` by default; use `--no-restart` to skip.

## Active Memory (reserved extension slot)

| Attribute | Value |
|-----------|-------|
| **What** | Proactive memory injection — agent surfaces relevant memories during conversation without explicit user request |
| **Config path** | `plugins.entries.active-memory` |
| **Status** | 🚧 Reserved in `FEATURES` dict; uncomment when needed |

When you're ready to manage active-memory, uncomment the stub in
`scripts/agent_memory.py` `FEATURES` dict and fill in the schema fields.

## Managed-environment config sync

Some OpenClaw deployments (notably K8s Pods) mirror the runtime
`~/.openclaw/openclaw.json` to extra paths for restart-survivability:

| Path | Purpose |
|------|---------|
| `~/.openclaw/openclaw.json` | Runtime config (always written) |
| `/app/clawconfig/openclaw.json` | Pod-restart source mirror (K8s) |
| `/app/k8s-config/clawconfig/openclaw.json` | K8s ConfigMap source mirror |

The script **auto-detects** the latter two by checking if their parent
directory exists. If you run OpenClaw locally (no `/app/...` paths), the
script silently skips them. No flag needed.

## Adding a new memory feature

1. Add an entry to `FEATURES` in `scripts/agent_memory.py`:

   ```python
   FEATURES["my-feature"] = {
       "path": ["plugins", "entries", "my-plugin", "config"],
       "enable_patch": {"enabled": True, "frequency": "0 * * * *"},
       "disable_patch": {"enabled": False},
       "check_key": "enabled",
       "status_key": "frequency",   # field shown in `status` output
       "description": "What this feature does",
       "supports_timezone": True,   # optional: enables --timezone for this feature
       "supports_half_life": False, # optional: enables --half-life
       "supports_max_age": False,   # optional: enables --max-age
   }
   ```

2. Add a section to this `features.md` documenting the new feature.

3. (Optional) Add feature-specific logic in `cmd_enable` for nested-field
   patches (see how `dreaming` writes `phases.deep`).

## Cross-references

- [OpenClaw memory docs](https://docs.openclaw.ai)
- [OpenClaw GitHub](https://github.com/openclaw/openclaw)

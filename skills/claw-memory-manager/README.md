# claw-memory-manager

> One-command management of OpenClaw Agent's built-in memory features —
> Dreaming consolidation today, more features coming.

## Why

[OpenClaw](https://docs.openclaw.ai) ships with a **Dreaming** mechanism
that runs scheduled memory consolidation. By default it's off — and enabling
it requires editing a 3-level nested JSON config, syncing to multiple paths
on managed deployments, and restarting the gateway. **This skill turns that
into one command.**

## What's Dreaming?

Each session your agent accumulates memory signals (things it recalled,
files it read, concepts it tagged). Most decay. But high-recall, high-context
items deserve to be **promoted to long-term `MEMORY.md`** so they survive
context resets.

Dreaming is a scheduled job that does that promotion automatically:

```
Light phase  → scan today's signals, score them
REM phase    → simulate recall, weight by frequency × recency × diversity
Deep phase   → top-scoring signals get written into MEMORY.md
```

Default schedule: 03:00 daily. Default half-life: 30 days.

## Quick start

```bash
# Check if your OpenClaw version supports dreaming
python3 scripts/agent_memory.py check dreaming

# See current state (enabled / disabled / params)
python3 scripts/agent_memory.py status dreaming

# Preview what enable would do (no writes)
python3 scripts/agent_memory.py enable dreaming --dry-run

# Enable with safe defaults (auto-backup, auto-restart)
python3 scripts/agent_memory.py enable dreaming

# Enable with custom params
python3 scripts/agent_memory.py enable dreaming \
    --half-life 14 \
    --max-age 30 \
    --timezone America/New_York

# Disable
python3 scripts/agent_memory.py disable dreaming
```

## Safety by default

| Layer | Behavior |
|-------|----------|
| **Backup** | Every write creates `openclaw.json.bak.<timestamp>` (opt out: `--no-backup`) |
| **Dry-run** | `--dry-run` shows exact JSON change + sync targets + restart plan |
| **Validate** | Half-life and max-age are range-checked (1-90 days) |
| **Auto-detect K8s** | Mirror paths (`/app/clawconfig/`, `/app/k8s-config/...`) auto-detected; no flag needed |
| **Verify** | After write, re-reads config to confirm before declaring success |
| **Restart** | Auto-runs `openclaw gateway restart` to apply (opt out: `--no-restart`) |

## Supported features

| Feature | Status |
|---------|--------|
| `dreaming` (memory consolidation) | ✅ Production |
| `active-memory` (proactive injection) | 🚧 Reserved extension slot |

To add a new feature, see the "Extending" section in
`references/features.md`.

## Requirements

- Python 3.8+
- OpenClaw 2026.4.24+ installed (`openclaw --version` to check)
- Write access to `~/.openclaw/openclaw.json`

Zero third-party Python dependencies (stdlib only).

## How it interacts with OpenClaw

The skill modifies one of three config files based on your environment:

| Environment | Path |
|-------------|------|
| Local install (`npm install -g openclaw`) | `~/.openclaw/openclaw.json` |
| Managed K8s Pod | Above + `/app/clawconfig/openclaw.json` + `/app/k8s-config/clawconfig/openclaw.json` |

The latter two mirrors exist because K8s Pods restore config from
ConfigMap on restart. The script syncs to all paths that exist, silently
skips ones that don't.

After write, it runs `openclaw gateway restart` to make changes take effect.

## Files

```
claw-memory-manager/
├── SKILL.md              ← agent-facing documentation
├── README.md             ← this file (human-facing)
├── LICENSE               ← MIT
└── scripts/
    └── agent_memory.py   ← single Python script, 400 LOC
└── references/
    └── features.md       ← feature catalog + schemas + extension guide
```

## License

MIT — see [LICENSE](./LICENSE).

## Author

Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)

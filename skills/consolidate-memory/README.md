# consolidate-memory

> Periodic housekeeping for an agent's memory files — merge duplicates, retire
> stale entries, fix relative dates, and prune a bloated `MEMORY.md` back
> under its size cap.

A **WorkBuddy-adapted** edition of the Claude Code `consolidate-memory` skill
(upstream: [claudskills.com/skills/consolidate-memory](https://claudskills.com/skills/consolidate-memory), MIT).

## Why

File-based agent memories already handle **incremental writes** — auto-log after
substantive work, distill logs older than 30 days. What they do *not* do is
clean up the **existing stock**: duplicated rules, expired one-off states,
"next week" references, and a `MEMORY.md` that has quietly grown past its own
size limit. This skill fills that gap. It is deliberately opt-in.

## Platform

| Platform | Use |
|---|---|
| WorkBuddy | This edition (three-layer memory: cloud profile / user-level `MEMORY.md` / workspace logs) |
| Claude Code / other agents | The upstream original — this edition hardcodes WorkBuddy paths and red lines |

## Install

```bash
# skills.sh CLI
npx -y skills add Songhonglei/better-agent-skills -s consolidate-memory

# Manual (WorkBuddy)
git clone https://github.com/Songhonglei/better-agent-skills.git
cp -r better-agent-skills/skills/consolidate-memory ~/.workbuddy/skills/
```

## Trigger

`整理记忆` · `记忆体检` · `记忆去重` · `压缩记忆` · `清理记忆` ·
`consolidate memory` · `memory health check` · `review memory`

## What it does

1. **Take stock** — locate both writable `MEMORY.md` files, measure with
   `wc -m`, tag every entry as duplicate / stale / relative-time /
   easy-to-refind / should-move-to-skill / keep, and report before changing
   anything.
2. **Consolidate** — merge overlaps, retire expired items, convert "last week"
   to `YYYY-MM-DD`, drop what a connected tool can re-derive, and move
   executable workflows into skills leaving a one-line pointer.
3. **Wrap up** — re-check size caps, confirm no log file was touched, and
   report exactly what changed.

## Safety rails

- Cloud memory (server-side profile) and `SOUL.md` / `USER.md` / `IDENTITY.md`
  are **read-only** — never touched.
- Daily logs are **append-only**. The platform's built-in 30-day distillation
  owns deletion; this skill only produces a candidate list.
- Never deletes the `.workbuddy` directory; never writes secrets or PII.
- Backs up each target as `MEMORY.md.bak-YYYYMMDD-HHMMSS` before writing.
- **One item at a time**: shows the full change list first, applies only what
  the user confirms, never batch-edits.

## How it differs from built-in memory features

| | Built-in | This skill |
|---|---|---|
| Trigger | Automatic (after work, 30-day distillation) | Explicit invocation |
| Scope | Incremental writes + archiving | Existing-stock audit |
| Dedup / conflict detection | Manual checklist only | Yes |
| Size cap enforcement | Soft cap, not enforced | `wc -m` verified |
| Deletion | Distills then removes old logs | Logs never deleted |

## Real-world run (2026-11-12)

A real pass took a user-level `MEMORY.md` from 6,427 → 3,975 characters
(cap: 4,000), merged 3 duplicate groups, retired one expired account state,
and moved ~10 lines of executable detail into a `dev-playbook` skill with a
pointer left behind. Zero information lost, both files backed up first.

## License

MIT — see [LICENSE](LICENSE).

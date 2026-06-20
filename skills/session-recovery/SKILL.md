---
name: session-recovery
description: >
  Recover lost agent session content and file changes from on-disk
  conversation logs. Streaming and OOM-safe on 700MB+ daily JSONL.
  Two commands: search.py for keyword search across recent sessions
  (with hit snippets, file-op listing, JSON for agent consumption);
  extract.py for pulling full write/edit content from a single session
  by ID prefix, with optional replay-rebuild for pure-edit sequences
  and safe restore-to-disk (refuses silent overwrites without --yes).
  Multi-agent aware via --agent main|all|a,b. Configurable data root
  via --root flag or SESSION_RECOVERY_ROOT env var (default
  ~/.openclaw/agents/). Trigger when user wants to find lost session
  content, recover files written by an agent, locate which session
  modified a file, search session history by keyword, or rebuild a
  file from an edit replay. Also triggers on 找回会话, 会话被覆盖,
  历史会话搜索, 文件被删了, session 丢了, 找回某个文件, 重放编辑.
---

# session-recovery

- **Version**: 1.0.1
- **License**: MIT
- **Author**: Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)
- **Repository**: https://github.com/Songhonglei/better-agent-skills

> Recover lost agent session content and file changes from on-disk conversation logs.
>
> 从本地会话日志中找回丢失的 agent 对话和文件改动。

Built for OpenClaw's on-disk session format (`~/.openclaw/agents/<agent>/sessions/*.jsonl`).
Streaming and OOM-safe for production-scale environments (5000+ sessions, 700MB+ daily JSONL).

## Compatibility

| Platform | Status |
|---|---|
| OpenClaw | ✅ Full (primary target) |
| Other agent frameworks (CC / Codex / Hermes) | 🛣️ Roadmap |
| Linux | ✅ Full |
| macOS | ✅ Full |
| Windows (WSL) | ✅ Full |
| Python | ≥ 3.8 (uses `pathlib`, `datetime.fromisoformat`) |

## Quick start

```bash
# Search recent sessions for a keyword
python3 scripts/search.py "index.html" --days 2

# Search by specific date, also list write/edit ops
python3 scripts/search.py "skill logo" --date 2026-06-13 --extract-files

# Search all agents
python3 scripts/search.py "anything" --agent all

# Filter by real msg timestamp (slower, more accurate when mtime lies)
python3 scripts/search.py "stuff" --days 7 --by-content-time

# JSON output for agent consumption
python3 scripts/search.py "stuff" --json

# Once you know the session ID, extract file ops
python3 scripts/extract.py 21f68359 --file-filter index.html

# Show full content (warning: can be large)
python3 scripts/extract.py 21f68359 --file-filter index.html --show-content

# Restore to original path (non-interactive needs --yes)
python3 scripts/extract.py 21f68359 --file-filter index.html --restore --yes

# Restore to a specific path
python3 scripts/extract.py 21f68359 --restore-to ~/out/index.html --yes

# Pure-edit session (no write baseline): replay edits to rebuild
python3 scripts/extract.py 21f68359 --file-filter app.py --rebuild \
    --restore-to ~/out/app.py --yes
```

## Custom data root

If your OpenClaw install puts agents elsewhere, override:

```bash
# Per-call
python3 scripts/search.py "foo" --root /custom/openclaw/agents

# Or environment variable
export SESSION_RECOVERY_ROOT=/custom/openclaw/agents
python3 scripts/search.py "foo"
```

Priority: `--root` > `SESSION_RECOVERY_ROOT` env > `~/.openclaw/agents/`.

## Data sources

Primary: **JSONL conversations** at `<root>/<agent>/sessions/*.jsonl` (always present).
Contains full tool calls, including `write` content and `edit` deltas.

Secondary (OpenClaw-specific): **QMD archive** at `<root>/<agent>/qmd/sessions/*.md`
(may not exist on all installs). Plain-text dialogue; survives session reset but
does NOT contain full code — use for finding *which* session, then extract from JSONL.

Recovery priority: `non-reset JSONL > reset+QMD > QMD only > reset only`.

## Safety

- **Restore refuses silent overwrites in non-TTY environments**. You must pass `--yes`
  to confirm in agent / CI / script contexts.
- **Target-already-exists is warned even with `--yes`** (writes are destructive).
- **`--show-content` prints full file content** which may be huge — prefer
  `--restore-to` for large files, or preview first.
- **`--max-files N` is an OOM guard** (default 300). When hit, output explicitly
  flags "may have missed results"; narrow the time window or raise the limit.

## Notes

- Session IDs support prefix match (first 8 hex chars usually enough).
- Time filter defaults to file `mtime`, which can lie if a session was last
  modified hours after its content was written. Use `--by-content-time` for
  accurate (slower) filtering by real message timestamps.
- `--limit` is *per agent, per source*. With `--agent all` total results
  multiply by agent count and source count.
- Field-name compatibility built in: `write/edit` ops accept any of
  `file_path|path`, `content|new_string|newText`, `oldText|old_string`,
  `arguments|input|parameters`.

## License

MIT (see LICENSE)

# recover-codex-project-chats

Safely diagnose and restore Codex Desktop conversations when project folders exist but show **No chats**, even though titles may still appear under **Recent**.

## Features

- Correlates `state_5.sqlite`, rollout JSONL, project assignments, configured model providers, and optional CSV snapshots.
- Detects the deceptively common provider-mismatch failure where Recent still has titles but every project looks empty.
- Performs read-only diagnosis while Codex is running and refuses offline repair until the desktop process is stopped.
- Creates a timestamped backup before changing provider metadata and verifies SQLite integrity and rollout coverage afterward.
- Documents recovery paths for lost assignments, moved workspaces, archived threads, and schema-compatible database restores.

## Install

### skills.sh / compatible agents

```bash
npx -y skills add Songhonglei/better-agent-skills -s recover-codex-project-chats
```

### ClawHub

```bash
clawhub install recover-codex-project-chats
```

### Manual

```bash
git clone https://github.com/Songhonglei/better-agent-skills.git
cp -R better-agent-skills/skills/recover-codex-project-chats ~/.codex/skills/
```

## Quick start

Ask your agent:

> Use `$recover-codex-project-chats` to diagnose why my Codex projects show no chats and restore them safely.

Or run the bundled diagnostic directly:

```bash
zsh scripts/codex_project_recovery.sh diagnose /path/to/codex_threads_snapshot.csv
```

The repair command is intentionally guarded and must only be used after diagnosis confirms that two provider names represent the same compatible backend:

```bash
# Quit Codex Desktop first.
zsh scripts/codex_project_recovery.sh repair-provider openai custom
zsh scripts/codex_project_recovery.sh verify
```

## Safety

- Never edit the live history database.
- Keep the generated backup until representative old chats open successfully.
- Do not rewrite provider metadata unless the old and current provider names point to a compatible backend.
- Inspect the actual SQLite schema before attempting row merges; Codex schemas can change.

## Requirements

macOS, Zsh, SQLite 3, jq, ripgrep, rsync, and Perl. The workflow targets Codex Desktop/ChatGPT Desktop local Codex data.

## License

MIT — see [LICENSE](LICENSE).

## Author

Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)

## Changelog

### v1.0.0 — 2026-08-06

- Initial public release.

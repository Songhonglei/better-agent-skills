---
name: recover-codex-project-chats
license: MIT
description: >
  Diagnose and safely repair Codex Desktop projects that exist but show “No chats/没有聊天”,
  while conversations may still appear under Recent. Use when users report missing project
  histories, lost thread-to-project mappings, model-provider changes, archived or invisible
  threads, moved cwd paths, incomplete ~/.codex restores, state_5.sqlite integrity or index
  problems, or need comparison against codex_threads_snapshot.csv or a ~/.codex backup.
---

# Recover Codex project chats

- **Version**: 1.0.1
- **License**: MIT
- **Author**: Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)
- **Repository**: https://github.com/Songhonglei/better-agent-skills/tree/main/skills/recover-codex-project-chats

Restore project visibility without overwriting the only copy of a conversation.

## Workflow

1. Run `scripts/codex_project_recovery.sh diagnose [csv-path]` while Codex may remain open. Save the output.
2. Read `references/incident-patterns.md` and classify the evidence before changing data.
3. Back up current `~/.codex`, the supplied backup, and Codex-related Application Support directories. Exclude only live Unix sockets.
4. Before any mutation, require Codex Desktop to be fully stopped. Confirm the app-server, renderer, and service processes are absent.
5. Run SQLite `PRAGMA integrity_check` on copies first. Inspect `.schema`; never invent columns.
6. Apply only the matching repair:
   - Provider mismatch: run `scripts/codex_project_recovery.sh repair-provider <old-provider> <current-provider>` after explaining the evidence. Repair only when both names refer to the same compatible backend.
   - Missing assignments: rebuild `thread-project-assignments` in `.codex-global-state.json` from actual thread IDs and cwd values. Preserve existing assignments. Resolve overlapping roots and temporary directories explicitly; do not rely solely on prefix matching.
   - Moved paths: create and review an old-cwd to current-project mapping before updating assignments or cwd metadata.
   - Missing database rows: merge only from a schema-compatible backup after integrity checks and a trial on copies.
7. Run `scripts/codex_project_recovery.sh verify` while Codex is stopped, then restart Codex and check each project in the UI.
8. Report root cause, backup paths, CSV rows, database rows, rollout files found, per-project visible counts, changed rows/files, and unrecovered thread IDs.

## Safety rules

- Treat `state_5.sqlite` plus WAL/SHM, rollout JSONL, `.codex-global-state.json`, and project metadata as one recovery set.
- Do not edit a live SQLite database.
- Do not replace all of `~/.codex` when a targeted repair is sufficient.
- Preserve archived state unless the user explicitly requests unarchiving.
- Do not change provider metadata merely to make rows visible unless the configured provider is compatible with the original sessions. Prefer restoring the provider configuration when compatibility is uncertain.
- Keep every pre-repair backup until the user verifies the UI and can open representative chats.

## Resources

- `scripts/codex_project_recovery.sh`: read-only diagnosis, guarded provider repair, and verification.
- `references/incident-patterns.md`: known failure patterns, schema landmarks, and evidence tests.

## Dependencies

- macOS with Codex Desktop or ChatGPT Desktop using the Codex runtime
- Zsh, SQLite 3, jq, ripgrep, rsync, and Perl
- Optional CSV snapshot or `~/.codex` backup for comparison

# multica-squad-load-balancer

Capability-aware, live-load dispatch for existing Multica squads, with worker-side delegation verification.

## What it does

- Resolves the project owner and its unique active squad at runtime.
- Filters workers by required skills, role, Agent/runtime availability and concurrency capacity, then selects the lowest active-task load.
- Uses plan → dispatch; dispatch posts one delegation mention and records squad activity.
- Requires workers to verify the captain, decision, selected identity and trigger comment before business execution.
- Preserves the original squad assignee, business permissions, approvals and result reporting thread.
- Stops for reconciliation when previous execution, completion, failure or uncertain writes exist.

## Install

```bash
npx skills add Songhonglei/better-agent-skills -s multica-squad-load-balancer
```

Or copy `skills/multica-squad-load-balancer` into your agent's skills directory. For managed setup, also install [multica-squad-onboard](../multica-squad-onboard).

Import a verified complete package of this skill into your Multica workspace, then add that workspace Skill UUID to the captain and every worker. Preserve existing business Skill assignments. Local installation alone does not prove remote runtime readiness.

## Read-only preview

```bash
python3 /path/to/multica-squad-load-balancer/scripts/squad_balance.py preview --project-id <project-UUID>
```

The CLI uses your existing login and default environment. Put explicit `--profile`, `--server-url` and `--workspace-id` overrides before the subcommand. Never share credentials across squad members.

## Runtime workflow

The captain follows [SKILL.md](./SKILL.md), checks the authorized task's capability requirements and uses the same conditions for `plan` and `dispatch`. Dispatch requires a real Multica captain run and its environment identity; do not simulate those variables to test writes.

Workers call `verify-worker` and store the binding in a private business directory outside the Skill installation, then execute the original authorized business and report in their triggering comment thread. No extra mention, child Issue, assignee change or automatic reassignment is required.

## Requirements and limits

Python 3.10+, a compatible logged-in `multica` CLI, permission to read project/squad/Agent/runtime/task-run/comment data, and for dispatch, permission to write captain comments and squad activity. Dispatch needs POSIX `fcntl` (Linux/macOS). See [the contract](./references/contract.md) for deployment fields, arguments and recovery boundaries. CLI diagnostics and delegation instructions currently use Chinese messages.

The local lock serializes the same Issue only on one host. There is no cross-machine exactly-once guarantee or atomic capacity reservation across Issues. Business authorization, claims, callbacks, idempotency, approvals and result acceptance remain the business system's responsibility.

The public package starts at **v1.0.0**. Its decision-record protocol remains **1.0.3** to preserve existing route hashes; the two versions serve different purposes. Protocol versions accepted by `verify-worker` are declared in the script and contract. Never delete state files or fabricate a legacy marker to bypass verification.

## Part of this suite

The [Agent Workflow](../../README.md#agent-workflow) section of [better-agent-skills](https://github.com/Songhonglei/better-agent-skills).

## Changelog

See [CHANGELOG.md](./CHANGELOG.md).

## License and author

MIT — see [LICENSE](./LICENSE). Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei).

# multica-squad-onboard

Prepare an existing Multica project and squad for capability-aware workload dispatch.

## What it does

- Takes a project ID or URL; reads the existing captain, members and assignments.
- Checks ownership, squad relationships, runtime bindings and concurrency limits.
- Adds the shared scheduler to the captain and workers without replacing their business skills.
- Adds different, project-scoped captain and worker instructions; preserves other project scopes.
- Supports explicitly authorized project-owner repair, private change plans, read-back verification and reconciliation after uncertain writes.
- Finishes with the scheduler's read-only preview, without creating Issues or dispatching business tasks.

## Install

Install this operator skill and the public scheduler from this repository:

```bash
npx skills add Songhonglei/better-agent-skills -s multica-squad-onboard -s multica-squad-load-balancer
```

Or copy both folders from `skills/` into your agent's skills directory. This GitHub release does not imply availability on another skill registry.

## Use

Ask your agent:

> Use multica-squad-onboard to onboard my existing Multica project: <project URL or UUID>.

Optionally provide a squad URL as a target constraint. Do not repeat the member list unless the current configuration is ambiguous. Check-only requests remain read-only. If the project owner must change, identify the intended captain and authorize that specific change.

The operator imports a verified complete scheduler package into the target Multica workspace and assigns it to the squad's captain and workers. Installing the operator skill locally does not deploy files into their remote runtimes.

For direct helper use, start with:

```bash
python3 /path/to/multica-squad-onboard/scripts/onboard.py --help
python3 /path/to/multica-squad-onboard/scripts/onboard.py inspect <project-UUID> --snapshot-file /path/to/private-evidence/before.json
```

Follow [SKILL.md](./SKILL.md) and [operations](./references/operations.md) for the inspect → prepare → apply workflow, source verification, project-owner repair and uncertain-result recovery.

## Requirements and limits

Python 3.10+, a logged-in compatible `multica` CLI and permission to read/configure the target workspace. An existing squad must contain its captain and at least one worker; the project's Agent owner must lead exactly one active squad. Missing or ambiguous relationships are reported rather than invented.

The CLI must expose the project, squad, Agent, runtime and Skill fields used by the helper. Verify compatibility with your deployment. The helper does not install or upgrade Multica itself. CLI diagnostics currently use Chinese messages.

Remote CLI/Python availability, scheduler files, writable business directories, business permissions and approvals need verification in the actual member runtimes. No business repository is mandatory; an unverified repository association is reported as unchecked. Code changes, deployment and business end-to-end tests are outside default onboarding scope.

## Verification

From the repository root, with pytest installed:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_multica_squad_onboard.py -q
```

These are synthetic tests and do not create remote tasks.

## Part of this suite

The [Agent Workflow](../../README.md#agent-workflow) section of [better-agent-skills](https://github.com/Songhonglei/better-agent-skills). Use [multica-squad-load-balancer](../multica-squad-load-balancer) for runtime scheduling.

## Changelog

See [CHANGELOG.md](./CHANGELOG.md).

## License and author

MIT — see [LICENSE](./LICENSE). Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei).

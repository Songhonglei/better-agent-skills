# openviking-projects

Give agents a shared, traceable view of local project knowledge with OpenViking. Register one global **openviking** MCP, then route each request by project code and absolute workspace path.

## What it covers

- Onboard a new macOS/Linux computer with Python 3.11+, a dedicated venv and fixed OpenViking 0.5.0. Windows uses WSL2.
- Install without GitHub through PyPI, TUNA or Aliyun mirrors; support a complete offline wheelhouse and pinned source mirrors.
- Check summary-model and embedding access separately, including vector dimensions and locally supplied credentials.
- Index reviewed project documents and selected sections, preserving source paths, content hashes and evidence dates.
- Share one read-only MCP across projects while retaining separate backend accounts by default.
- Synchronize changed sources with locks, journals, original-source readbacks and a five-file incremental change limit. Unchanged sources create no model jobs.
- Configure login startup and weekday synchronization when requested, after project verification.

The skill manages project documents. Chat capture and conversation-memory hooks are separate, optional integrations.

## Install the skill

With a compatible skills installer:

```sh
npx -y skills add Songhonglei/better-agent-skills -s openviking-projects
```

Or copy this directory into your agent's skill directory. For Codex:

```sh
git clone https://github.com/Songhonglei/better-agent-skills.git
mkdir -p ~/.codex/skills
cp -R better-agent-skills/skills/openviking-projects ~/.codex/skills/
```

If GitHub is unavailable, transfer a trusted archive of this skill directory. OpenViking itself can be installed through the package mirrors without cloning GitHub. See [INSTALL.md](INSTALL.md) and [network-install.md](references/network-install.md).

## Ask your agent

```text
Use $openviking-projects to install or reuse OpenViking on this computer and onboard this project.
Inspect existing deployments first. Use a trusted package mirror if GitHub is unavailable.
Use the model configuration I identify locally; do not ask me to paste credentials into chat.
Review the document whitelist, verify both models, and test real MCP find/read calls.
```

For a manual preflight, run from this skill directory:

```sh
python3 scripts/ovk.py preflight
python3 scripts/ovk.py install --index tuna --dry-run
```

Continue with [onboarding.md](references/onboarding.md). Model endpoints, model names, embedding dimensions and credential references must come from your own environment. A Codex account login does not provide an embedding service.

## Architecture and boundaries

One global `openviking` MCP serves all registered projects. Use `resolve_project` for the current absolute workspace, then supply `project_code` and `workspace_path` on every find/read/list/tree call. Adding a project does not register another MCP.

Project accounts are independent by default. Explicitly choosing a shared account gives up native account isolation; MCP routing still checks project scopes. Data defaults to `~/.openviking-projects`, outside the skill. Existing deployments are preserved, and a newer skill does not silently overwrite an installed runtime.

Generated summaries are leads. Read the original source URI and check dates before relying on a conclusion. A snapshot does not prove current production state or grant permission to perform actions. A stale or unavailable index falls back to local files.

## Validation

```sh
python3 scripts/selftest.py
python3 scripts/selftest.py --native-python /path/to/openviking-venv/bin/python --report /local/results.json
```

The release has 19 offline regression checks. Native OpenViking 0.5.0 was also tested with three synthetic projects and local fake models, including MCP calls, pagination, incremental sync and six directed cross-account denials. That test reuses existing dependencies; it is not a fresh installation test on every OS or a measurement of semantic accuracy or whole-task token savings.

See [validation.md](references/validation.md) for acceptance criteria and [cli.md](references/cli.md) for parameters, status codes and recovery.

## License and version

MIT © 2026 Evan Song. See [LICENSE](LICENSE) and [CHANGELOG.md](CHANGELOG.md).

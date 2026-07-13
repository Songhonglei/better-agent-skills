# better-agent-skills

> Skill suite for getting more out of your AI agent ([OpenClaw](https://github.com/openclaw/openclaw), [Hermes](#), Claude Code, Codex CLI, Cursor, Cline, and more).

A growing, security-conscious collection of portable agent skills — from
zero-dependency environment diagnostics to cross-tool memory transfer and
multi-agent coordination. All authored by **Evan Song** (@Songhonglei).

[![Skills](https://img.shields.io/badge/skills-12-blue)](https://github.com/Songhonglei/better-agent-skills/tree/main/skills)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Author](https://img.shields.io/badge/author-Evan%20Song-orange)](https://github.com/Songhonglei)

---

## 🧩 Skills in this suite

> Categorization follows the Better Agent canonical taxonomy — Agent Memory & Boot / Agent Identity & Profile / Workspace & Session / Cross-container Coordination.

### 🧠 Agent Memory & Boot

| Skill | Latest | What it does |
|-------|--------|--------------|
| [`init‑hooks`](skills/init-hooks) | **v1.0.0** | Run scripts automatically on every container/host boot — survives gateway restarts, container restarts and rebuilds. Registry-driven, idempotent, with inline / local-script / remote-CDN hook types. |
| [`subagent‑timeout‑config`](skills/subagent-timeout-config) | **v1.0.0** | One-click subagent timeout configurator for OpenClaw with preset profiles. |
| [`claw‑memory‑manager`](skills/claw-memory-manager) | **v1.1.0** | One-command management of OpenClaw built-in memory features. Configure Dreaming (Light→REM→Deep auto consolidation) with tunable half-life, max-age, IANA timezone. |

### 🪪 Agent Identity & Profile

| Skill | Latest | What it does |
|-------|--------|--------------|
| [`copy‑my‑profile`](skills/copy-my-profile) | **v1.0.0** | Portable Markdown profile for AI tools — like vCard for AI assistants. Extract once from Tool A, paste into Tool B. Supports 10+ tools. |
| [`agent‑avatar‑manager`](skills/agent-avatar-manager) | **v1.0.1** | Manage your OpenClaw Agent's avatar. Send an image/URL, or describe a style and let Freepik vector search pick. |
| [`rename‑session`](skills/rename-session) | **v1.0.0** | Rename or auto-generate a friendly session label. Random label generator (zh/en with locale auto-detect), multi-agent auto-detection. |

### 🗃️ Workspace & Session

| Skill | Latest | What it does |
|-------|--------|--------------|
| [`workspace‑git‑setup`](skills/workspace-git-setup) | **v1.0.3** | One-command Git tracking with a security-focused `.gitignore` (credentials / TLS / SSH keys auto-excluded), large-file guard, and `--audit` mode. |
| [`session‑recovery`](skills/session-recovery) | **v1.0.1** | Recover lost agent session content and file changes from on-disk conversation logs. Streaming and OOM-safe on 700MB+ daily logs. |
| [`token‑slim`](skills/token-slim) | **v1.0.0** | Guided token optimization for agent workspaces — identifies bloat, recommends slimming, supports beast mode. |
| [`hello‑env`](skills/hello-env) | **v1.0.2** | Zero-dependency Bash environment health check for Linux, macOS, containers, K8s pods. |
| [`collective‑memory`](skills/collective-memory) | **v1.0.0** | Broadcast a single memory note to multiple AI agent workspaces in one shot — upserts into MEMORY.md / AGENTS.md / TOOLS.md. |

### 🌐 Cross-container Coordination

| Skill | Latest | What it does |
|-------|--------|--------------|
| [`agent‑team‑mesh`](skills/agent-team-mesh) | **v1.0.0** | Team-wide P2P mesh for OpenClaw agents running on different containers/pods. Each gateway listens on its own pod for direct WebSocket calls. |

---

## 📦 Install

Three ways to install, pick what fits your agent:

### Option 1 — ClawHub (recommended for OpenClaw users)

```bash
clawhub install <skill-name>
# e.g.
clawhub install hello-env
clawhub install claw-memory-manager
```

### Option 2 — skills.sh CLI (works for Claude Code, Cursor, Cline, Continue, OpenClaw, and 30+ other agents)

```bash
npx -y skills add Songhonglei/better-agent-skills -s <skill-name>
# e.g.
npx -y skills add Songhonglei/better-agent-skills -s copy-my-profile
```

### Option 3 — Direct from GitHub

```bash
# Clone the whole suite
git clone https://github.com/Songhonglei/better-agent-skills.git
cp -r better-agent-skills/skills/<skill-name> /path/to/your/agent/skills/

# Or just one skill via curl + tar
curl -sL https://github.com/Songhonglei/better-agent-skills/archive/refs/heads/main.tar.gz | \
  tar -xzf - --strip-components=2 better-agent-skills-main/skills/<skill-name>
```

---

## 🎯 Use cases

| Scenario | Try |
|----------|-----|
| New machine setup, want quick env diagnostic | [`hello‑env`](skills/hello-env) |
| Worried about losing workspace history | [`workspace‑git‑setup`](skills/workspace-git-setup) |
| Switching from Tool A to Tool B, don't want to retrain | [`copy‑my‑profile`](skills/copy-my-profile) |
| Agent runs out of context too fast | [`token‑slim`](skills/token-slim) |
| Want agent to remember things better across days | [`claw‑memory‑manager`](skills/claw-memory-manager) |
| Lost conversation history after crash | [`session‑recovery`](skills/session-recovery) |
| Multiple agents need to share knowledge | [`collective‑memory`](skills/collective-memory) |
| Multiple agents need to call each other | [`agent‑team‑mesh`](skills/agent-team-mesh) |
| Subagent keeps timing out | [`subagent‑timeout‑config`](skills/subagent-timeout-config) |
| Want to give your agent a personalized look | [`agent‑avatar‑manager`](skills/agent-avatar-manager) |
| Sessions all have terrible default names | [`rename‑session`](skills/rename-session) |
| Init logic keeps getting lost on container rebuild | [`init‑hooks`](skills/init-hooks) |

---

## 🛡️ Quality standards

Every skill in this suite follows these standards:

- **Zero secret leakage** — automated scan before publish
- **Cross-platform** — Linux + macOS + (where applicable) Windows-via-WSL/Git-Bash
- **Locale-aware** — language defaults from `$LC_ALL` / `$LC_MESSAGES` / `$LANG`, not hardcoded
- **Safe defaults** — auto-backup before write, `--dry-run` for high-risk ops, validate before sync
- **Portable frontmatter** — `name + description` only, ≤1024 bytes (works on strict YAML parsers like Qoder)
- **Real attribution** — `**Author**` / `**Repository**` / `**License**` in every SKILL.md body
- **Single dependency budget** — pure stdlib (Python) or pure Bash where possible

---

## 📚 Related ecosystems

- [OpenClaw](https://github.com/openclaw/openclaw) — open-source agent framework (most skills target this primarily)
- [ClawHub](https://clawhub.com) — public skill marketplace
- [skills.sh](https://www.skills.sh) — multi-agent skill installer (`npx skills`)
- [Anthropic Skills spec](https://docs.anthropic.com) — the underlying SKILL.md format

---

## 🤝 Contributing

Want to fork a skill, file an issue, or suggest improvements? Open an issue
or PR on this repo. For new skills, start by reading any existing skill's
`SKILL.md` to see the conventions used.

---

## 👤 Author

**Evan Song** — [github.com/Songhonglei](https://github.com/Songhonglei)

Built and maintained as part of daily AI-agent productivity work; skills are
released here as they stabilize.

## 📄 License

MIT © 2026 Evan Song — see [LICENSE](LICENSE).

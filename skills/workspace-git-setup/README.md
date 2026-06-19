# workspace-git-setup

> One command to set up safe, sensible Git tracking for any working directory — with a built-in security audit.

A zero-dependency Bash script that initializes Git version control for a project, ships a battle-tested security `.gitignore`, warns about large files before your first commit, and can audit an existing repo for leaked secrets and untracked files.

**Pure `bash` + `git`. No Python, no npm, no third-party packages.**

---

## Why

Setting up Git for a new project usually means:
- copy-pasting a `.gitignore` from somewhere (and hoping it covers secrets),
- accidentally committing a `.env`, a private key, or a 200MB model file,
- never noticing that half your files were never `git add`-ed.

`workspace-git-setup` does all of that for you, safely and idempotently.

---

## Quick start

```bash
# Clone the repo, then run inside your project:
git clone https://github.com/Songhonglei/workspace-git-setup.git
bash workspace-git-setup/scripts/setup.sh
```

Or grab just the script with `curl` and run it in the current directory:

```bash
curl -fsSL https://raw.githubusercontent.com/Songhonglei/workspace-git-setup/main/scripts/setup.sh -o setup.sh
bash setup.sh
```

That's it. It will:
1. `git init` (skipped if a repo already exists; default branch `main`),
2. write a security-focused `.gitignore`,
3. set `core.autocrlf=input` to avoid CRLF noise,
4. warn you about any file larger than 10MB before committing,
5. make the first commit.

### Specify a path and project name

```bash
bash scripts/setup.sh /path/to/project "MyProject"
```

### Path & identity resolution

| What | Priority |
|------|----------|
| Workspace path | CLI argument → `WORKSPACE_DIR` env var → current directory |
| Git identity | `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` env vars → existing git config → interactive prompt |

If you provide an email but no name, the email prefix is used as the username.

```bash
GIT_AUTHOR_NAME="Jane Doe" GIT_AUTHOR_EMAIL="jane@example.com" bash scripts/setup.sh
```

---

## Three modes

| Mode | What it does | Mutates? |
|------|--------------|----------|
| *(default)* | init + `.gitignore` + large-file warning + first commit | ✏️ yes |
| `--audit` | read-only health check: tracked secrets, untracked files, config | 👀 no |
| `--dry-run` | preview every action without applying anything | 👀 no |

### Audit an existing repo

```bash
bash scripts/setup.sh --audit
```

Outputs three checks (read-only, never modifies anything):

1. **Sensitive files** — lists private keys / tokens / credentials already tracked by Git (leak risk). It only *warns* — it never runs destructive commands for you.
2. **Untracked files** — files neither `add`-ed nor ignored, so you can decide.
3. **Config** — whether `core.autocrlf` is sane and `.gitignore` exists.

### Preview before applying

```bash
bash scripts/setup.sh --dry-run
```

---

## What the `.gitignore` covers

| Category | Patterns |
|----------|----------|
| Credentials | `.env`, `.env.*`, `*.pem`, `secrets/`, `.credentials/`, `*token*.json`, `*secret*.json` |
| TLS / SSH keys | `**/certs/*.key`, `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519`, `*.p12`, `*.keystore` |
| Temp / cache | `tmp/`, `*.tmp`, `*.cache`, `*.log`, `*.pid` |
| OS / editor | `.DS_Store`, `._*`, `Thumbs.db`, `.vscode/`, `.idea/`, `*.swp` |
| Dependencies | `node_modules/`, `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `.pytest_cache/` |
| Build output | `output/`, `dist/`, `build/`, `out/`, `*.egg-info/` |

> Note: it scopes private-key ignores to `**/certs/*.key` (instead of a blanket `*.key`) so it won't accidentally hide legitimate `.key` files elsewhere.

---

## Design notes

- **Idempotent** — run it as many times as you like; existing config is preserved, not clobbered. If a `.gitignore` already exists, it shows a diff and asks before overwriting.
- **No surprises** — large files (>10MB) trigger a confirmation prompt before the first commit, so you don't bloat your repo by accident.
- **Local only** — it does not add a remote. Add one yourself when ready:
  ```bash
  git remote add origin <your-repo-url>
  ```

---

## Requirements

- `git` — https://git-scm.com/downloads
- `bash` 4.0+
- `coreutils` (`numfmt`/`stat`/`realpath`) — preinstalled on most Unix-like systems; `numfmt` is optional (falls back to raw byte counts).

---

## Author

**Evan Song** — [github.com/Songhonglei](https://github.com/Songhonglei)

## License

MIT © 2026 Evan Song — see [LICENSE](LICENSE).

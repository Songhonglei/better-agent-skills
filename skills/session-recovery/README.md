# session-recovery

> Recover lost agent session content and file changes from on-disk conversation logs.
> 从本地会话日志中找回丢失的 agent 对话和文件改动。

[English](#english) · [中文](#中文)

Built for **OpenClaw** session format. Streaming and OOM-safe on 700MB+ daily JSONL
(real production scale: 5000+ sessions). Other agent frameworks (Claude Code, Codex,
Hermes) are on the roadmap.

---

## English

### Why

Agent sessions get lost: someone resets a session, a config change rotates the
on-disk logs, your editor's `--restore` workflow needs to find the right session
out of thousands. This skill scans the raw JSONL conversation files (and OpenClaw's
optional QMD archive) to find sessions by keyword, list every `write`/`edit` operation,
and optionally replay edits to rebuild a file.

### Install

Drop the folder into your skills directory:

```bash
git clone https://github.com/Songhonglei/better-agent-skills.git /tmp/bas
cp -r /tmp/bas/skills/session-recovery ~/.claude/skills/   # or wherever
```

Or install via `clawhub`:

```bash
npx -y clawhub install session-recovery
```

Or via `skills.sh`:

```bash
npx -y skills add Songhonglei/better-agent-skills/skills/session-recovery
```

### Usage

```bash
# Search the last 2 days for a keyword
python3 scripts/search.py "index.html" --days 2

# Pin to a date, also list write/edit ops
python3 scripts/search.py "skill logo" --date 2026-06-13 --extract-files

# JSON output (for agents)
python3 scripts/search.py "anything" --json

# Extract everything one session touched
python3 scripts/extract.py 21f68359

# Filter by path substring
python3 scripts/extract.py 21f68359 --file-filter index.html

# Restore to original path (non-interactive needs --yes)
python3 scripts/extract.py 21f68359 --file-filter index.html --restore --yes

# Replay edits to rebuild when no write baseline
python3 scripts/extract.py 21f68359 --file-filter app.py --rebuild \
    --restore-to ~/out/app.py --yes
```

### Custom data root

```bash
python3 scripts/search.py "foo" --root /custom/openclaw/agents
# or
export SESSION_RECOVERY_ROOT=/custom/openclaw/agents
```

Priority: `--root` > env > default `~/.openclaw/agents/`.

### Safety

- Restore refuses silent overwrites in non-TTY environments; pass `--yes` to confirm.
- "Target file exists" warned even with `--yes` (writes are destructive).
- `--max-files N` is an OOM guard (default 300); when hit, output flags "may have missed".

### Compatibility

| Platform | Status |
|---|---|
| OpenClaw | ✅ Full (primary target) |
| Other agent frameworks (CC/Codex/Hermes) | 🛣️ Roadmap |
| Linux / macOS / WSL | ✅ Full |
| Python ≥ 3.8 | Required (`pathlib`, `datetime.fromisoformat`) |

---

## 中文

### 用途

会话丢失场景：被 reset、被覆盖、改了配置丢了路径、想从几千个会话里找出"上次改 index.html 的那个"。
本工具扫原始 JSONL 对话日志（OpenClaw 还有可选的 QMD 归档），按关键词找会话、列所有
`write`/`edit` 操作，可重放 edit 重建文件。

### 安装

```bash
git clone https://github.com/Songhonglei/better-agent-skills.git /tmp/bas
cp -r /tmp/bas/skills/session-recovery ~/.claude/skills/   # 或别处
```

或者通过 clawhub / skills.sh 一键装。

### 常用命令

```bash
# 搜近 2 天
python3 scripts/search.py "index.html" --days 2

# 指定日期 + 列文件操作
python3 scripts/search.py "skill logo" --date 2026-06-13 --extract-files

# JSON 输出（给 agent）
python3 scripts/search.py "anything" --json

# 看会话改了什么
python3 scripts/extract.py 21f68359 --file-filter index.html

# 恢复到原路径
python3 scripts/extract.py 21f68359 --file-filter index.html --restore --yes

# 纯 edit 序列重放重建
python3 scripts/extract.py 21f68359 --rebuild --restore-to ~/out/app.py --yes
```

### 自定义数据根

```bash
python3 scripts/search.py "foo" --root /custom/openclaw/agents
# 或
export SESSION_RECOVERY_ROOT=/custom/openclaw/agents
```

优先级：`--root` > 环境变量 > 默认 `~/.openclaw/agents/`。

### 安全约束

- 非交互环境必须显式 `--yes` 才会写文件（拒绝静默覆盖）
- 目标文件已存在时即使带 `--yes` 也会明确告警
- `--max-files N` 是 OOM 兜底（默认 300），达上限会提示"可能漏检"

### 兼容矩阵

| 平台 | 支持 |
|---|---|
| OpenClaw | ✅ 完整 |
| Claude Code / Codex / Hermes | 🛣️ Roadmap |
| Linux / macOS / WSL | ✅ |
| Python ≥ 3.8 | 需要 |

---

## License

MIT © Evan Song · [github.com/Songhonglei](https://github.com/Songhonglei)

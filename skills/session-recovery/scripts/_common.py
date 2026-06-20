#!/usr/bin/env python3
"""
session-recovery: _common.py
Shared utilities for searching/extracting OpenClaw agent session content.

Designed for production scale (5000+ sessions, 700MB+ daily JSONL):
- Never read entire JSONL into memory; chunked byte-level pre-filter
- Stream line-by-line with json.loads, skip malformed lines silently
- Timestamp dual-format: ISO 8601 strings + millisecond epochs
- Field name compatibility: write/edit accept arguments|input|parameters,
  file_path|path, content|new_string|newText, oldText|old_string

Data root discovery (priority order):
  1. CLI flag --root <path>           (passed in via resolve_data_root)
  2. Env var SESSION_RECOVERY_ROOT    (override for non-standard installs)
  3. ~/.openclaw/agents/              (OpenClaw default)
"""

import os
import json
from pathlib import Path
from datetime import datetime, timezone

# Default OpenClaw agents root. Override with SESSION_RECOVERY_ROOT env var
# or --root CLI flag if your install uses a different layout.
DEFAULT_AGENTS_ROOT = Path.home() / ".openclaw" / "agents"
DEFAULT_AGENT = "main"


def resolve_data_root(cli_root=None):
    """
    Resolve the agents data root using priority:
      CLI flag > env var SESSION_RECOVERY_ROOT > default (~/.openclaw/agents)
    Returns a Path; does NOT verify the directory exists (caller handles that
    so we can give a friendly error message).
    """
    if cli_root:
        return Path(cli_root).expanduser()
    env_root = os.environ.get("SESSION_RECOVERY_ROOT")
    if env_root:
        return Path(env_root).expanduser()
    return DEFAULT_AGENTS_ROOT


# ---------------------------------------------------------------------------
# Agent discovery
# ---------------------------------------------------------------------------
def list_agents(agents_root=None):
    """Return all agents under agents_root that have a sessions/ dir (sorted)."""
    root = agents_root or DEFAULT_AGENTS_ROOT
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "sessions").exists():
            out.append(d.name)
    return out


def resolve_agents(agent_arg, agents_root=None):
    """
    agent_arg:
      - None / "main" -> ["main"] (if it exists)
      - "all"         -> every agent discovered
      - "a,b,c"       -> specific list
    Returns only agents that actually exist on disk.
    """
    avail = list_agents(agents_root)
    if not agent_arg:
        wanted = [DEFAULT_AGENT]
    elif agent_arg.lower() == "all":
        return avail
    else:
        wanted = [a.strip() for a in str(agent_arg).split(",") if a.strip()]
    return [a for a in wanted if a in avail]


def has_qmd(agent_dir):
    """Some OpenClaw installs lack the QMD archive. Returns (exists, count)."""
    qd = agent_dir / "qmd" / "sessions"
    if not qd.exists():
        return (False, 0)
    return (True, sum(1 for _ in qd.glob("*.md")))


# ---------------------------------------------------------------------------
# Timestamp parsing (dual format)
# ---------------------------------------------------------------------------
def parse_ts(val):
    """
    Parse an OpenClaw timestamp into an aware datetime(UTC).

    Supports:
      - millisecond epoch int/str (e.g. 1781341244085)
      - second epoch (10 digits)
      - ISO 8601 string (e.g. 2026-06-13T08:50:24.810Z)
    Returns None on parse failure.
    """
    if val is None:
        return None
    # Numeric epoch
    if isinstance(val, (int, float)) or (isinstance(val, str) and val.isdigit()):
        n = float(val)
        if n > 1e12:      # milliseconds
            n /= 1000.0
        try:
            return datetime.fromtimestamp(n, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    # ISO 8601 string
    if isinstance(val, str):
        s = val.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def msg_ts(d):
    """Pull timestamp from a message dict: prefer message.timestamp, fall back to outer."""
    t = None
    m = d.get("message")
    if isinstance(m, dict):
        t = m.get("timestamp")
    if t is None:
        t = d.get("timestamp")
    return parse_ts(t)


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "?"


# ---------------------------------------------------------------------------
# Field compatibility (tool call input)
# ---------------------------------------------------------------------------
def tool_input(c):
    """toolCall input dict: arguments (new) > input (old) > parameters."""
    inp = c.get("arguments") or c.get("input") or c.get("parameters") or {}
    return inp if isinstance(inp, dict) else {}


def tool_path(inp):
    return inp.get("file_path") or inp.get("path") or "?"


def tool_content(inp):
    """write uses content; edit uses new_string/newText."""
    return (inp.get("content") or inp.get("new_string") or
            inp.get("newText") or inp.get("new_text") or "")


def tool_old(inp):
    return inp.get("oldText") or inp.get("old_string") or inp.get("old_text") or ""


# ---------------------------------------------------------------------------
# Streaming readers (OOM-safe)
# ---------------------------------------------------------------------------
def file_contains_bytes(path, needles_lower):
    """
    Byte-level coarse filter: does the raw file contain any of the keywords
    (lowercased)? Reads in 8MB chunks with overlap to avoid loading the whole
    file and to catch needles that straddle chunk boundaries.

    needles_lower: list[bytes] (already lowercased utf-8 bytes)
    """
    if not needles_lower:
        return True
    maxlen = max(len(n) for n in needles_lower)
    overlap = b""
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(8 * 1024 * 1024)
                if not chunk:
                    break
                buf = (overlap + chunk).lower()
                for n in needles_lower:
                    if n in buf:
                        return True
                overlap = chunk[-(maxlen - 1):] if maxlen > 1 else b""
    except OSError:
        return False
    return False


def iter_jsonl(path):
    """Yield parsed dicts line by line; skip malformed lines. Never reads whole file."""
    try:
        with open(path, "r", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except OSError:
        return


def iter_messages(path):
    """Yield only type=='message' lines."""
    for d in iter_jsonl(path):
        if d.get("type") == "message":
            yield d


def session_meta(path):
    """Read first-line session metadata (cwd / sessionKey / started). First line only."""
    try:
        with open(path, "r", errors="ignore") as f:
            first = f.readline()
        d = json.loads(first)
        if d.get("type") == "session":
            return {
                "cwd": d.get("cwd", ""),
                "sessionKey": d.get("sessionKey", ""),
                "started": fmt(parse_ts(d.get("timestamp"))),
            }
    except Exception:
        pass
    return {}

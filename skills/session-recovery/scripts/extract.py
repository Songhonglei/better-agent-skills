#!/usr/bin/env python3
"""
session-recovery: extract.py
Extract full write/edit content from a given session, optionally restore to disk.

Streaming refactor for production scale (line-by-line, no whole-file reads).
Supports: multi-agent auto-locate, edit replay rebuild, --json, --yes.

Usage:
  python3 extract.py <session-id> [--file-filter index.html]
  python3 extract.py 21f68359 --file-filter index.html --show-content
  python3 extract.py 21f68359 --file-filter index.html --restore --yes
  python3 extract.py 21f68359 --restore-to ~/out/index.html --yes
  python3 extract.py 21f68359 --agent all --json

Args:
  --root PATH            agents data root (default: ~/.openclaw/agents/;
                         also reads SESSION_RECOVERY_ROOT env var)
  --agent main|all|a,b   which agent(s) to search (default: main)
  --file-filter PATH     only show ops whose path contains this substring
  --restore              restore last write / rebuild result to original path
  --restore-to PATH      restore to a specific path
  --rebuild              replay pure-edit sequence (no write baseline)
  --show-content         print full content (large files = large output)
  --yes                  skip restore confirmation (required for non-TTY)
  --json                 JSON output
"""

import os
import sys
import json
import argparse
from pathlib import Path

from _common import (
    resolve_data_root, resolve_agents, list_agents, has_qmd, fmt, msg_ts,
    tool_input, tool_path, tool_content, tool_old, iter_messages,
)
import re


def parse_args():
    p = argparse.ArgumentParser(
        description="Extract file operations from an agent session (OpenClaw).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("session_id", help="Session ID (prefix match, e.g. 21f68359)")
    p.add_argument("--root", help="Agents data root (default: ~/.openclaw/agents/; "
                                  "also reads SESSION_RECOVERY_ROOT env var)")
    p.add_argument("--file-filter", help="Only extract ops whose path contains this substring")
    p.add_argument("--agent", default="main", help="Agent: main|all|a,b (default: main)")
    p.add_argument("--restore", action="store_true", help="Restore content to original path")
    p.add_argument("--restore-to", help="Restore to specific path")
    p.add_argument("--rebuild", action="store_true", help="Replay pure-edit sequence (no write baseline)")
    p.add_argument("--show-content", action="store_true", help="Print full content")
    p.add_argument("--yes", action="store_true", help="Skip restore confirmation (non-TTY required)")
    p.add_argument("--json", action="store_true", help="JSON output")
    return p.parse_args()


def find_session(agents, session_id, agents_root):
    """
    Look up a session across agents by prefix.
    Priority: non-reset JSONL > reset+QMD > QMD > reset only.
    Returns (kind, path, agent) or (None, None, None).
    """
    best = None  # (rank, kind, path, agent) -- lower rank wins
    for agent in agents:
        ad = agents_root / agent
        sdir = ad / "sessions"
        qdir = ad / "qmd" / "sessions"
        jsonl = reset = qmd = None
        if sdir.exists():
            for f in sdir.glob("*.jsonl"):
                if ".reset." not in f.name and f.stem.startswith(session_id):
                    jsonl = f
                    break
            if not jsonl:
                for f in sdir.glob(f"{session_id}*.reset.*"):
                    reset = f
                    break
        if qdir.exists():
            for f in qdir.glob("*.md"):
                if f.stem.startswith(session_id):
                    qmd = f
                    break
        cand = None
        if jsonl:
            cand = (0, "jsonl", jsonl, agent)
        elif reset and qmd:
            cand = (1, "reset+qmd", qmd, agent)
        elif qmd:
            cand = (2, "qmd", qmd, agent)
        elif reset:
            cand = (3, "reset", reset, agent)
        if cand and (best is None or cand[0] < best[0]):
            best = cand
    if best is None:
        return (None, None, None)
    return (best[1], best[2], best[3])


def extract_from_jsonl(jsonl_file, file_filter):
    """流式提取所有 write/edit（保留顺序，供重放）。"""
    ops = []
    for d in iter_messages(jsonl_file):
        if d.get("message", {}).get("role") != "assistant":
            continue
        mt = msg_ts(d)
        for c in (d.get("message", {}).get("content") or []):
            if not isinstance(c, dict) or c.get("type") != "toolCall":
                continue
            if c.get("name") not in ("write", "edit"):
                continue
            inp = tool_input(c)
            path = tool_path(inp)
            if file_filter and file_filter.lower() not in path.lower():
                continue
            ops.append({
                "source": "JSONL", "ts": fmt(mt), "tool": c["name"], "path": path,
                "content": tool_content(inp), "old_text": tool_old(inp),
            })
    return ops


def extract_from_qmd(qmd_file, file_filter):
    text = qmd_file.read_text(errors="ignore")
    ops = []
    pat = r'(write|edit)\s*[->]\s*([^\s(]+(?:\.html|\.py|\.md|\.json|\.js|\.css|\.txt|\.sh)[^\s(]*)\s*\((\d+)\s*chars?\)'
    for m in re.finditer(pat, text, re.IGNORECASE):
        path = m.group(2)
        if file_filter and file_filter.lower() not in path.lower():
            continue
        ops.append({
            "source": "QMD", "tool": m.group(1), "path": path, "content": "",
            "note": "QMD stores conversation text only, not full code. Source dialogue: " + str(qmd_file),
        })
    if not ops:
        ops.append({
            "source": "QMD", "tool": "N/A",
            "path": f"(no QMD entry matched '{file_filter}')" if file_filter else "(full transcript)",
            "content": "" if file_filter else text,
            "note": f"QMD has dialogue text only; code cannot be auto-recovered. Inspect: {qmd_file}",
        })
    return ops


def rebuild_from_edits(ops):
    """
    对单个文件按时间顺序重放：write 设为基线，edit 在基线上做 old→new 替换。
    返回 (rebuilt_text, applied, failed)；无 write 基线则从空串起（best-effort）。
    """
    text = None
    applied = 0
    failed = 0
    for op in ops:
        if op["tool"] == "write":
            text = op.get("content", "")
            applied += 1
        elif op["tool"] == "edit":
            old = op.get("old_text", "")
            new = op.get("content", "")
            if text is None:
                text = ""  # 无基线，best-effort
            if old and old in text:
                text = text.replace(old, new, 1)
                applied += 1
            else:
                failed += 1
    return text, applied, failed


def print_ops(ops, show_content=False):
    if not ops:
        print("  No matching file operations found.")
        return
    print(f"\n  Found {len(ops)} file operations:\n")
    for i, op in enumerate(ops, 1):
        print(f"  [{i}] {op['tool'].upper()} -> {op['path']}")
        if op.get("ts"):
            print(f"       Time: {op['ts']}")
        if op.get("note"):
            print(f"       Note: {op['note']}")
        content = op.get("content", "")
        if content and op["path"] not in ("(full transcript)",):
            if show_content:
                print(f"       Content ({len(content)} chars):\n")
                print(content)
                print()
            else:
                print(f"       Preview ({len(content)} chars): {content[:300].replace(chr(10),' ')}...")
        print()


def do_restore(ops, restore_to, yes, rebuild):
    fileable = [o for o in ops if o.get("tool") in ("write", "edit")]
    if not fileable:
        print("  No restorable file operations.")
        return

    # Restore always targets a single logical file: pick the last-touched path
    # and replay only ops for that path to avoid cross-file interference.
    target_path = fileable[-1]["path"]
    same = [o for o in fileable if o["path"] == target_path]
    if len({o["path"] for o in fileable}) > 1:
        print(f"  INFO: Session touched multiple files; this run only restores: {target_path}")
        print(f"        (use --file-filter to pick another)")

    write_ops = [o for o in same if o.get("tool") == "write" and o.get("content")]
    edit_ops = [o for o in same if o.get("tool") == "edit"]
    src_path = target_path
    final_content = None
    method = None

    if write_ops:
        last = write_ops[-1]
        idx = same.index(last)
        trailing = [o for o in same[idx:] if o["tool"] in ("write", "edit")]
        if len(trailing) > 1 and rebuild:
            final_content, ap, fa = rebuild_from_edits(trailing)
            method = f"write + replay {len(trailing)-1} edits (applied {ap} / failed {fa})"
        else:
            final_content = last["content"]
            method = "last write"
    elif edit_ops and rebuild:
        final_content, ap, fa = rebuild_from_edits(same)
        method = f"pure edit replay (applied {ap} / failed {fa}, no write baseline, best-effort)"
    else:
        print("  No restorable full content.")
        if edit_ops:
            print("     Only edit deltas, no write baseline -- add --rebuild to attempt replay (not guaranteed).")
        return

    target = os.path.expanduser(restore_to or src_path)
    tp = Path(target)
    exists = tp.exists()
    print(f"  Restore plan: {src_path} -> {target}")
    print(f"  Method: {method}  |  size: {len(final_content)} chars")
    if exists:
        # Overwriting is destructive; warn explicitly even with --yes.
        print(f"  WARN: Target exists ({tp.stat().st_size} bytes), will be overwritten.")
    if not yes:
        if not sys.stdin.isatty():
            print("  Non-interactive and no --yes given; aborted (refusing silent overwrite).")
            return
        prompt = "  Confirm overwrite? [y/N] " if exists else "  Confirm restore? [y/N] "
        if input(prompt).strip().lower() != "y":
            print("  Cancelled.")
            return
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(final_content)
    print(f"  Restored to {target}")


def main():
    args = parse_args()
    agents_root = resolve_data_root(args.root)
    if not agents_root.exists():
        msg = (f"Data root not found: {agents_root}\n"
               f"  Override with --root <path> or env SESSION_RECOVERY_ROOT.\n"
               f"  Default is ~/.openclaw/agents/")
        print(json.dumps({"error": msg}) if args.json else msg)
        sys.exit(1)

    agents = resolve_agents(args.agent, agents_root)
    if not agents:
        avail = list_agents(agents_root)
        msg = (f"Agent not found: {args.agent}. "
               f"Available: {', '.join(avail) or '(none)'} under {agents_root}")
        print(json.dumps({"error": msg}) if args.json else msg)
        sys.exit(1)

    kind, sfile, agent = find_session(agents, args.session_id, agents_root)
    if kind is None:
        msg = f"Session not found: {args.session_id} (searched agents: {', '.join(agents)})"
        print(json.dumps({"error": msg}) if args.json else msg)
        sys.exit(1)

    if kind == "reset":
        msg = f"WARN: Session {args.session_id} JSONL was reset and no QMD backup; code unrecoverable."
        print(json.dumps({"error": msg}) if args.json else msg)
        sys.exit(1)

    if kind in ("qmd", "reset+qmd"):
        ops = extract_from_qmd(sfile, args.file_filter)
    else:
        ops = extract_from_jsonl(sfile, args.file_filter)

    if args.json:
        print(json.dumps({
            "session_id": args.session_id, "agent": agent, "kind": kind,
            "data_root": str(agents_root),
            "file": str(sfile), "ops": ops,
        }, ensure_ascii=False, indent=2))
        return

    print(f"Session file: {sfile}")
    print(f"   agent: {agent}  |  source: {kind.upper()}")
    if kind == "reset+qmd":
        print("   WARN: JSONL was reset, using QMD dialogue text (no full code)")
    print_ops(ops, show_content=args.show_content)

    if args.restore or args.restore_to:
        do_restore(ops, args.restore_to, args.yes, args.rebuild)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
session-recovery: search.py
Search QMD + JSONL session logs for lost conversation/file-change content.

Engineered for production-scale environments (5000+ sessions, 700MB+ daily
JSONL) with streaming OOM-safe scanning: never load whole files; byte-level
pre-filter then line-by-line parse.

Usage:
  python3 search.py "keyword1 keyword2" [--date 2026-06-13] [--days 2]
  python3 search.py "index.html" --date 2026-06-13 --extract-files
  python3 search.py "skill" --agent all --json
  python3 search.py "skill" --by-content-time   # filter by real msg timestamp

Args:
  --root PATH            agents data root (default: ~/.openclaw/agents/;
                         also reads SESSION_RECOVERY_ROOT env var)
  --agent main|all|a,b   which agent(s) to search (default: main)
  --days N               look back N days (default: 2)
  --date YYYY-MM-DD      anchor date in UTC
  --limit N              max results per agent per source (default: 10)
  --max-files N          max files to scan, OOM guard (default: 300)
  --by-content-time      filter by real msg timestamp instead of file mtime
                         (slower, more accurate; bypasses mtime window and
                         pre-filters all files — burns scan budget faster,
                         consider increasing --max-files)
  --extract-files        also list write/edit operations
  --json                 structured JSON output (for agent consumption)
"""

import re
import sys
import json
import argparse
from datetime import datetime, timedelta, timezone

from _common import (
    resolve_data_root, resolve_agents, has_qmd, list_agents,
    parse_ts, msg_ts, fmt, tool_input, tool_path, tool_content,
    file_contains_bytes, iter_messages, iter_jsonl,
)


# Per-file size cap. Files bigger than this are skipped to bound worst-case
# scan latency (one 1GB session.bak.jsonl can dominate total time).
OVERSIZED_BYTES = 64 * 1024 * 1024


def parse_args():
    p = argparse.ArgumentParser(
        description="Search historical agent session content (OpenClaw).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("keywords", nargs="+", help="Search keywords (space-separated, OR logic)")
    p.add_argument("--root", help="Agents data root (default: ~/.openclaw/agents/; "
                                  "also reads SESSION_RECOVERY_ROOT env var)")
    p.add_argument("--date", help="Anchor date YYYY-MM-DD (UTC)")
    p.add_argument("--days", type=int, default=2, help="Look back N days (default: 2)")
    p.add_argument("--agent", default="main", help="Agent: main|all|a,b (default: main)")
    p.add_argument("--limit", type=int, default=10,
                   help="Max results per agent per source (default: 10; "
                        "with multiple agents, total = limit x agents x sources)")
    p.add_argument("--max-files", type=int, default=300,
                   help="Max files to scan, OOM guard (default: 300)")
    p.add_argument("--by-content-time", action="store_true",
                   help="Filter by real msg timestamp (slower, more accurate)")
    p.add_argument("--extract-files", action="store_true",
                   help="Also list write/edit operations")
    p.add_argument("--json", action="store_true", help="JSON output")
    return p.parse_args()


def get_date_range(date_str, days):
    """
    Build [start, end) time window in UTC.

    - With --date YYYY-MM-DD: window is `days` days ending on that date
      (anchor = that day at 00:00 UTC; end = anchor + 1 day).
    - Without --date: anchor is *today* at 00:00 UTC (not 'now'), so
      --days N gives 'today plus N-1 prior days'; end = now + 1 minute
      so freshly-written files are included.
    """
    if date_str:
        anchor = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = anchor + timedelta(days=1)
    else:
        now = datetime.now(timezone.utc)
        anchor = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Include files modified up to "now + 1 minute" to absorb clock skew
        # between filesystem and process clock.
        end = now + timedelta(minutes=1)
    start = anchor - timedelta(days=days - 1)
    return start, end


def in_window(mtime, start, end):
    return start <= mtime <= end


def search_qmd(agent, agent_dir, keywords, start, end, limit):
    qmd_dir = agent_dir / "qmd" / "sessions"
    if not qmd_dir.exists():
        return []
    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    needles = [k.lower().encode("utf-8") for k in keywords]
    results = []
    for md in sorted(qmd_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True):
        mtime = datetime.fromtimestamp(md.stat().st_mtime, tz=timezone.utc)
        if not in_window(mtime, start, end):
            continue
        if not file_contains_bytes(md, needles):
            continue
        text = md.read_text(errors="ignore")  # QMD 是对话文本，通常较小
        matches = pattern.findall(text)
        if not matches:
            continue
        snippets = []
        for m in pattern.finditer(text):
            s = max(0, m.start() - 150)
            e = min(len(text), m.end() + 150)
            snippets.append("..." + text[s:e].replace("\n", " ").strip() + "...")
            if len(snippets) >= 3:
                break
        fu = re.search(r"User: .*?(\[.*?GMT\+8\].*?)(?=\nAssistant:|$)", text, re.DOTALL)
        summary = fu.group(1)[:150].strip() if fu else "(无摘要)"
        results.append({
            "source": "QMD", "agent": agent, "session_id": md.stem, "file": str(md),
            "mtime": fmt(mtime), "hit_count": len(matches), "summary": summary,
            "snippets": snippets,
        })
    results.sort(key=lambda r: -r["hit_count"])
    return results[:limit]


def search_jsonl(agent, agent_dir, keywords, start, end, limit,
                 extract_files, by_content_time, max_files, budget):
    sessions_dir = agent_dir / "sessions"
    if not sessions_dir.exists():
        return [], budget
    pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
    needles = [k.lower().encode("utf-8") for k in keywords]
    results = []

    files = sorted(sessions_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    for jf in files:
        if budget["scanned"] >= max_files:
            budget["hit_limit"] = True
            break
        # Skip rotated / backup files. These are not live sessions and can be
        # huge (we've seen 1GB+ session.bak.jsonl files that dominate scan time).
        # A user who really wants them in scope can rename them.
        name = jf.name
        if (".reset." in name or ".bak." in name or
                name.endswith(".bak") or name.endswith(".bak.jsonl") or
                name.startswith("session.bak")):
            continue
        mtime = datetime.fromtimestamp(jf.stat().st_mtime, tz=timezone.utc)
        # mtime coarse filter: when by_content_time is on, the window is just
        # a hint (a session can be modified hours after its content), so we
        # rely on content-time filter below; otherwise enforce strict mtime.
        if not by_content_time and not in_window(mtime, start, end):
            continue
        # Soft cap on single-file size to keep worst-case latency bounded.
        # Anything bigger than 64MB is almost certainly a rotated/backup or
        # a runaway session. Record and report in the final summary, do NOT
        # spam stderr mid-scan (one warning per file gets lost in long output).
        try:
            fsize = jf.stat().st_size
        except OSError:
            continue
        if fsize > OVERSIZED_BYTES:
            budget["oversized"].append({
                "path": str(jf),
                "name": jf.name,
                "size_bytes": fsize,
                "size_mb": fsize // (1024 * 1024),
                "mtime": fmt(mtime),
                "agent": agent,
            })
            continue
        # byte-level coarse filter before full parse
        if not file_contains_bytes(jf, needles):
            continue
        budget["scanned"] += 1

        snippets = []
        file_ops = []
        content_hit_in_window = False
        for d in iter_messages(jf):
            role = d.get("message", {}).get("role")
            mt = msg_ts(d)
            for c in (d.get("message", {}).get("content") or []):
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text" and role == "user":
                    t = c.get("text", "")
                    if pattern.search(t):
                        if by_content_time and mt and in_window(mt, start, end):
                            content_hit_in_window = True
                        if len(snippets) < 3:
                            snippets.append(f"[user] {t[:200].strip()}")
                if extract_files and role == "assistant" and c.get("type") == "toolCall" \
                        and c.get("name") in ("write", "edit"):
                    inp = tool_input(c)
                    cont = tool_content(inp)
                    # file_ops 同样参与内容时间过滤（见 UGLIC L2）
                    if by_content_time and mt and in_window(mt, start, end):
                        content_hit_in_window = True
                    file_ops.append({
                        "ts": fmt(mt), "tool": c["name"], "path": tool_path(inp),
                        "content_len": len(cont), "content_preview": cont[:300],
                    })
        if not snippets and not file_ops:
            continue
        # 内容时间模式：任何命中（snippets 或 file_ops）都不在窗口内则跳过
        if by_content_time and (snippets or file_ops) and not content_hit_in_window:
            continue
        results.append({
            "source": "JSONL", "agent": agent, "session_id": jf.stem, "file": str(jf),
            "mtime": fmt(mtime), "hit_count": len(snippets) + len(file_ops),
            "snippets": snippets, "file_ops": file_ops,
        })
    results.sort(key=lambda r: -r["hit_count"])
    return results[:limit], budget


def print_human(all_results, keywords, notes, budget):
    total = len(all_results)
    print(f"\nSearch keywords: {' | '.join(keywords)}")
    for n in notes:
        print(n)
    print(f"Found {total} matching sessions\n")
    all_results.sort(key=lambda r: r["mtime"], reverse=True)
    for i, r in enumerate(all_results, 1):
        print("=" * 60)
        print(f"[{i}] {r['mtime']}  [{r['source']}/{r['agent']}]  session {r['session_id'][:8]}...")
        print(f"     hits: {r['hit_count']}  |  file: {r['file']}")
        if r.get("summary"):
            print(f"\n  Summary: {r['summary'][:150]}")
        if r.get("snippets"):
            print("\n  Snippets:")
            for s in r["snippets"][:2]:
                print(f"     {s[:200]}")
        if r.get("file_ops"):
            print(f"\n  File ops ({len(r['file_ops'])} write/edit):")
            for op in r["file_ops"][:5]:
                print(f"     [{op['ts']}] {op['tool']} -> {op['path']} ({op['content_len']} chars)")
                if op["content_preview"]:
                    print(f"       preview: {op['content_preview'][:100].strip()}...")
    print("=" * 60 + "\n")
    if budget.get("hit_limit"):
        print(f"  WARN: scan limit reached ({budget['scanned']} files, --max-files). May have missed results.")
        print("        Narrow time range (--date / smaller --days) or raise --max-files.\n")

    # Oversized-file report (collected during scan; printed once at the end so
    # users can see exactly which files were skipped without scrolling).
    oversized = budget.get("oversized", [])
    if oversized:
        threshold_mb = OVERSIZED_BYTES // (1024 * 1024)
        total_skipped_mb = sum(o["size_mb"] for o in oversized)
        plural = "files" if len(oversized) > 1 else "file"
        print(f"  WARN: skipped {len(oversized)} oversized {plural} (>{threshold_mb}MB), "
              f"totaling {total_skipped_mb}MB:")
        for o in sorted(oversized, key=lambda x: -x["size_bytes"]):
            print(f"     - {o['size_mb']:>5}MB  [{o['agent']}]  {o['name']}")
            print(f"              path:  {o['path']}")
            print(f"              mtime: {o['mtime']}")
        print("        These are likely rotated backups (.bak / .reset) or runaway sessions.")
        print(f"        If you really need to search them, raise the threshold by editing")
        print(f"        OVERSIZED_BYTES in scripts/search.py.\n")

    if not all_results:
        print("  No matches found. Suggestions:")
        print("    1. Broader keywords")
        print("    2. Increase --days or specify --date")
        print("    3. Try --agent all to search all agents")
        if any("No QMD" in n for n in notes):
            print("    4. No QMD on this install -- reset sessions are unrecoverable\n")
        else:
            print()


def main():
    args = parse_args()
    keywords = args.keywords
    if len(keywords) == 1 and " " in keywords[0]:
        keywords = keywords[0].split()

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

    start, end = get_date_range(args.date, args.days)
    notes = [f"Time window: {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')} (UTC)"
             f"  |  agents: {', '.join(agents)}"
             f"  |  filter: {'content-time' if args.by_content_time else 'file-mtime'}"]

    budget = {"scanned": 0, "hit_limit": False, "oversized": []}
    all_results = []
    qmd_missing_agents = []
    for agent in agents:
        agent_dir = agents_root / agent
        ok, cnt = has_qmd(agent_dir)
        if not ok:
            qmd_missing_agents.append(agent)
        else:
            all_results += search_qmd(agent, agent_dir, keywords, start, end, args.limit)
        jres, budget = search_jsonl(
            agent, agent_dir, keywords, start, end, args.limit,
            args.extract_files, args.by_content_time, args.max_files, budget)
        all_results += jres
        if budget["hit_limit"]:
            break

    if qmd_missing_agents:
        notes.append(f"No QMD source (JSONL only): {', '.join(qmd_missing_agents)}")

    if args.json:
        print(json.dumps({
            "keywords": keywords, "agents": agents,
            "data_root": str(agents_root),
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "scanned_files": budget["scanned"], "hit_scan_limit": budget["hit_limit"],
            "skipped_oversized": budget.get("oversized", []),
            "oversized_threshold_mb": OVERSIZED_BYTES // (1024 * 1024),
            "qmd_missing": qmd_missing_agents,
            "results": all_results,
        }, ensure_ascii=False, indent=2))
    else:
        print_human(all_results, keywords, notes, budget)


if __name__ == "__main__":
    main()

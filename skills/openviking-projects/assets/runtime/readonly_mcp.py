"""Four read-only tools confined to one explicit project resource subtree."""
from __future__ import annotations

import json
import hashlib
import os
import time
import re
from pathlib import Path
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(os.environ.get('OVK_HOME', str(Path.home() / '.openviking-projects'))) / 'cache/tiktoken'))
import tiktoken
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pilot_state import ROOT, SCOPE, PROJECT_ID, StateError, fresh_state, load_policy, state_lock

from project_registry import SERVICE_ROOT
BASE = json.loads((SERVICE_ROOT / 'configs/service.json').read_text())['url']
ENCODING = tiktoken.get_encoding("o200k_base")
mcp = FastMCP(PROJECT_ID + "-readonly", instructions=(
    "Read-only project snapshots. Known paths/symbols: use local files/rg first. "
    "For cross-document questions use find, then read the source URI and cite it. "
    "Check evidence dates and authority; summaries do not establish live state. "
    "Continue pages with snapshot_id as expected_snapshot and returned offsets. "
    "On stale/unavailable index fall back to local files. Scope: " + SCOPE))
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
SETTINGS = load_policy(ROOT)
FIND_BUDGET = SETTINGS["budgets"]["find"]
DIRECTORY_BUDGET = SETTINGS["budgets"]["directory"]
READ_DEFAULT_BUDGET = SETTINGS["budgets"]["read_default"]
READ_MAX_BUDGET = SETTINGS["budgets"]["read_max"]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def scoped(uri):
    parsed = urlsplit(uri)
    if parsed.scheme != "viking" or parsed.netloc != "resources" or parsed.query or parsed.fragment:
        raise ValueError("Only the selected project resource URI is permitted.")
    if unquote(uri) != uri or any(part in {".", ".."} for part in parsed.path.split("/")):
        raise ValueError("Encoded paths and relative path segments are not permitted.")
    normalized = uri.rstrip("/")
    if normalized != SCOPE and not normalized.startswith(SCOPE + "/"):
        raise ValueError("This tool cannot access another project or memory namespace.")
    return normalized


def bounded(value, budget=1200):
    """Legacy plain-text helper for the offline A/B script, not MCP responses."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    tokens = ENCODING.encode(text)
    if len(tokens) > budget:
        text = ENCODING.decode(tokens[:budget - 35]) + "\n[Output limited; request a narrower URI or line window.]"
    return text


def json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def text_tokens(text):
    return ENCODING.encode(text, disallowed_special=())


def within_budget(value, budget):
    return len(text_tokens(json_text(value))) <= budget


def preview(text, budget=180):
    tokens = text_tokens(text)
    return ENCODING.decode(tokens[:budget], errors="ignore"), len(tokens) > budget


def read_page(content, *, uri, offset, char_offset, limit, budget, snapshot_id="", source=None):
    """Fit complete JSON; continuation positions are lines plus Unicode characters."""
    lines = content.splitlines(keepends=True)
    if char_offset > (len(lines[0]) if lines else 0):
        raise ValueError("char_offset exceeds the current line; use the returned continuation.")
    window = lines[:limit]
    text = "".join(window)[char_offset:]
    more_lines = len(lines) > limit

    def document(chunk):
        remaining = char_offset + len(chunk)
        advance = 0
        for line in window:
            if remaining < len(line):
                break
            remaining -= len(line)
            advance += 1
        token_cut = len(chunk) < len(text)
        has_more = token_cut or more_lines
        return {"uri": uri, "offset": offset, "char_offset": char_offset, "content": chunk,
                "truncated": has_more, "has_more": has_more,
                "truncation_reason": "token_budget" if token_cut else "line_limit" if more_lines else None,
                "next_offset": offset + advance if has_more else None,
                "next_char_offset": remaining if has_more else None, "token_budget": budget,
                "snapshot_id": snapshot_id, "source": source}

    full = document(text)
    if within_budget(full, budget):
        return full
    low, high = 0, len(text)
    best = document("")
    while low <= high:
        end = (low + high) // 2
        candidate = document(text[:end])
        if within_budget(candidate, budget):
            best = candidate
            low = end + 1
        else:
            high = end - 1
    # Prefer a complete line when it fits, retaining character continuation for long lines.
    line_end = best["content"].rfind("\n") + 1
    if line_end:
        candidate = document(best["content"][:line_end])
        if within_budget(candidate, budget):
            best = candidate
    if text and not best["content"]:
        raise ValueError("The response metadata exceeds the budget; use a shorter URI.")
    return best


def directory_page(payload, *, uri, offset, limit, level_limit=None, snapshot_id=""):
    entries = payload["result"]
    if not isinstance(entries, list):
        raise RuntimeError("Unexpected directory response.")
    if not entries and payload.get("has_more"):
        raise RuntimeError("Directory pagination made no progress.")
    for entry in entries:
        scoped(entry["uri"])

    def document(items):
        has_more = bool(payload.get("has_more")) or len(items) < len(entries)
        metadata_cut = any(item.get("metadata_truncated") for item in items)
        result = {"uri": uri, "offset": offset, "entries": items, "returned_count": len(items),
                  "truncated": has_more or metadata_cut, "has_more": has_more,
                  "truncation_reason": "token_budget" if len(items) < len(entries) else "entry_limit" if has_more else "metadata_budget" if metadata_cut else None,
                  "next_offset": offset + len(items) if has_more else None,
                  "token_budget": DIRECTORY_BUDGET, "snapshot_id": snapshot_id}
        if level_limit is not None:
            result["level_limit"] = level_limit
        return result

    selected = []
    for entry in entries[:limit]:
        candidate = document(selected + [entry])
        if not within_budget(candidate, DIRECTORY_BUDGET):
            if not selected:
                # A pathological abstract must not prevent forward progress.
                entry = {key: entry[key] for key in ("uri", "isDir", "size") if key in entry}
                entry["metadata_truncated"] = True
                if not within_budget(document([entry]), DIRECTORY_BUDGET):
                    raise ValueError("A directory URI exceeds the budget; use a narrower URI.")
                selected.append(entry)
            break
        selected.append(entry)
    return document(selected)


def check_snapshot(receipt, uri, expected_snapshot, continuation):
    name = uri.rsplit("/", 1)[-1]
    version = receipt["fingerprints"].get(name, receipt["snapshot_id"])
    if continuation and not expected_snapshot:
        raise StateError("Continuation requires expected_snapshot from the previous page.")
    if expected_snapshot and (not re.fullmatch(r"[a-f0-9]{64}", expected_snapshot) or expected_snapshot != version):
        raise StateError("Snapshot changed; restart from offset=0 with the new snapshot.")
    return version


def request(path, *, params=None, body=None, transform, budget, expected_snapshot="", continuation=False):
    with state_lock(ROOT):
        manifest, receipt = fresh_state(ROOT)
        uri = (params or {}).get("uri", (body or {}).get("target_uri", SCOPE))
        version = check_snapshot(receipt, uri, expected_snapshot, continuation)
        lookup = {s["curated_file"]: s for s in manifest["sources"]}
        source = lookup.get(uri.rsplit("/", 1)[-1])
        provenance = {key: source.get(key) for key in ("source_path", "source_role", "source_sha256", "evidence_date")} if source else None
        context = {"manifest": manifest, "receipt": receipt, "snapshot_id": version, "source": provenance}
        result = perform_request(path, params=params, body=body, transform=transform, budget=budget, context=context)
        after_manifest, after_receipt = fresh_state(ROOT)
        if after_receipt["snapshot_id"] != receipt["snapshot_id"]:
            raise StateError("Index changed during lookup; restart the lookup.")
        return result


def perform_request(path, *, params, body, transform, budget, context):
    config = json.loads((ROOT / "configs/ovcli-reader.conf").read_text())
    headers = {"Authorization": "Bearer " + config["api_key"], "Content-Type": "application/json"}
    url = BASE + path + ("?" + urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    started = time.monotonic()
    try:
        with build_opener(NoRedirect).open(Request(url, data=data, headers=headers), timeout=5) as response:
            payload = json.load(response)
        if payload.get("status") != "ok":
            raise RuntimeError("OpenViking did not return a successful result.")
        value = transform(payload, context)
        if not within_budget(value, budget):
            raise RuntimeError("Response exceeds the requested token budget.")
        result = json_text(value)
        metric = {"operation": path, "elapsed_ms": round((time.monotonic() - started) * 1000),
                  "output_tokens": len(text_tokens(result)), "budget_tokens": budget,
                  "truncated": bool(value.get("truncated")), "ok": True}
        with (ROOT / "evidence/mcp-usage.jsonl").open("a") as log:
            log.write(json.dumps(metric) + "\n")
        return result
    except StateError:
        raise
    except Exception as exc:
        # Avoid including URLs, headers, credentials or response bodies in MCP errors.
        raise RuntimeError(f"Pilot lookup unavailable ({type(exc).__name__}); use local files and rg.") from None


@mcp.tool(annotations=READ_ONLY)
def find(query: str, target_uri: str = SCOPE, limit: int = SETTINGS["find_default_limit"]) -> str:
    """Find evidence: default 3 hits, maximum 8, 3000-token JSON budget. Read source URIs for full text."""
    target_uri = scoped(target_uri)
    if not query.strip() or len(query) > 600:
        raise ValueError("Use a non-empty query of at most 600 characters.")
    limit = min(SETTINGS["find_max_limit"], max(1, limit))
    current_entry = bool(re.search(r"workid|入口|发布目标", query, re.I)) and not re.search(r"历史|当时|截至|20\d{2}[-年]", query)
    def sources(payload, context):
        manifest = context["manifest"]
        lookup = {source["curated_file"]: source for source in manifest["sources"]}
        result = []
        hits = payload["result"].get("resources", [])
        if current_entry:
            hits = sorted(hits, key=lambda hit: (lookup.get(hit["uri"].rsplit("/", 1)[-1], {}).get("priority", 0),
                lookup.get(hit["uri"].rsplit("/", 1)[-1], {}).get("evidence_date") or "", hit.get("score", 0)), reverse=True)
        for hit in hits[:limit]:
            uri = scoped(hit["uri"])
            source = lookup.get(uri.rsplit("/", 1)[-1], {})
            summary, truncated = preview(hit.get("abstract", ""))
            result.append({"uri": uri, "source_path": source.get("source_path"),
                           "source_role": source.get("source_role", "source-policy"),
                           "evidence_date": source.get("evidence_date"),
                           "snapshot_id": context["receipt"]["fingerprints"].get(uri.rsplit("/", 1)[-1], context["receipt"]["snapshot_id"]),
                           "score": round(hit.get("score", 0), 4),
                           "generated_summary": summary, "summary_truncated": truncated})
        document = {"snapshot_live_verified": False, "requested_limit": limit,
                    "corpus_snapshot_id": context["receipt"]["snapshot_id"],
                    "ranking_policy": "current_entry_authority_date_then_similarity" if current_entry else "semantic_similarity",
                    "instruction": "Summaries are leads. Read source URIs for full text; latest AGENTS and entry evidence take priority over historical records.",
                    "sources": result, "token_budget": FIND_BUDGET}
        # Shrink previews evenly before dropping any requested source metadata.
        summary_budget = 180
        while True:
            document["truncated"] = any(item["summary_truncated"] for item in result)
            document["truncation_reason"] = ("token_budget" if summary_budget < 180 else "summary_preview") if document["truncated"] else None
            if within_budget(document, FIND_BUDGET):
                return document
            if not summary_budget:
                raise ValueError("Source metadata exceeds the budget; request fewer hits.")
            summary_budget //= 2
            for item in result:
                item["generated_summary"], clipped = preview(item["generated_summary"], summary_budget)
                item["summary_truncated"] |= clipped
    return request("/api/v1/search/find", body={"query": query, "target_uri": target_uri,
                   "limit": SETTINGS["find_max_limit"] if current_entry else limit,
                   "level": 2, "read_content": False}, transform=sources, budget=FIND_BUDGET)


@mcp.tool(annotations=READ_ONLY)
def read(uri: str, offset: int = 0, limit: int = 200,
         token_budget: int = READ_DEFAULT_BUDGET, char_offset: int = 0, expected_snapshot: str = "") -> str:
    """Read JSON pages: default 4000 tokens, request up to 15000. offset is a 0-based line;
    continue with next_offset, next_char_offset AND snapshot_id as expected_snapshot.
    A later page requires expected_snapshot. limit is 1-1000 lines per page.
    This snapshot does not establish live system state.
    """
    uri = scoped(uri)
    if offset < 0 or char_offset < 0 or not 1 <= limit <= 1000 or not 512 <= token_budget <= READ_MAX_BUDGET:
        raise ValueError("Use nonnegative offsets, limit 1-1000, and token_budget 512-15000.")
    return request("/api/v1/content/read", params={"uri": uri, "offset": offset, "limit": limit + 1},
                   transform=lambda payload, context: read_page(payload["result"], uri=uri, offset=offset,
                       char_offset=char_offset, limit=limit, budget=token_budget,
                       snapshot_id=context["snapshot_id"], source=context["source"]), budget=token_budget,
                   expected_snapshot=expected_snapshot, continuation=bool(offset or char_offset))


@mcp.tool(name="list", annotations=READ_ONLY)
def list_entries(uri: str = SCOPE, offset: int = 0, limit: int = 30, expected_snapshot: str = "") -> str:
    """List 3000-token JSON pages. Continue with next_offset and snapshot_id as expected_snapshot."""
    uri = scoped(uri)
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("Use a nonnegative offset and limit 1-200.")
    return request("/api/v1/fs/ls", params={"uri": uri, "node_limit": limit, "offset": offset,
                   "sort_by": "name", "sort_order": "asc", "include_overview": "false", "abs_limit": 120},
                   transform=lambda payload, context: directory_page(payload, uri=uri, offset=offset, limit=limit,
                       snapshot_id=context["snapshot_id"]), budget=DIRECTORY_BUDGET,
                   expected_snapshot=expected_snapshot, continuation=bool(offset))


@mcp.tool(annotations=READ_ONLY)
def tree(uri: str = SCOPE, offset: int = 0, limit: int = 40, expected_snapshot: str = "") -> str:
    """Show 2 levels in 3000-token JSON pages. Continue with next_offset and snapshot_id as expected_snapshot."""
    uri = scoped(uri)
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("Use a nonnegative offset and limit 1-200.")
    return request("/api/v1/fs/tree", params={"uri": uri, "node_limit": limit, "offset": offset,
                   "level_limit": 2, "include_overview": "false", "abs_limit": 100},
                   transform=lambda payload, context: directory_page(payload, uri=uri, offset=offset, limit=limit,
                       level_limit=2, snapshot_id=context["snapshot_id"]), budget=DIRECTORY_BUDGET,
                   expected_snapshot=expected_snapshot, continuation=bool(offset))


if __name__ == "__main__":
    mcp.run(transport="stdio")

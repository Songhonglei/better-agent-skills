"""Local, read-only operations dashboard for the existing OpenViking runtime."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

HOME = Path(os.environ.get("OVK_HOME", str(Path.home() / ".openviking-projects"))).resolve()
STATIC = Path(__file__).parent / "static"
ZONE = ZoneInfo("Asia/Shanghai")
app = FastAPI(title="OpenViking 本地监控", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
_cache: dict = {}
_cache_lock = asyncio.Lock()


def load(path: Path, default=None, required=False):
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
    except (OSError, ValueError):
        if required:
            raise ValueError(f"无法读取本机配置 {path.name}") from None
        return {} if default is None else default


def entries():
    try:
        registry = load(HOME / "configs/projects.json", required=True)
        projects = registry["projects"]
        if not isinstance(projects, dict):
            raise ValueError("Invalid project registry")
        return projects
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, "项目注册表无法读取，请检查本机配置") from None


def project(code: str):
    entry = entries().get(code)
    if entry is None:
        raise HTTPException(404, "项目未登记")
    try:
        root = Path(entry["data_root"]).resolve()
    except (KeyError, TypeError, ValueError, OSError):
        raise HTTPException(409, "项目状态目录配置异常") from None
    if not root.is_relative_to(HOME / "projects"):
        raise HTTPException(409, "项目状态目录不在登记范围内")
    return entry, root


def secret_values():
    values = list(load(HOME / "configs/provider-keys.json").values())
    try:
        values.append((HOME / "configs/root.key").read_text().strip())
    except OSError:
        pass
    for entry in entries().values():
        if not isinstance(entry, dict) or not isinstance(entry.get("data_root"), str):
            continue
        root = Path(entry["data_root"]).resolve()
        if root.is_relative_to(HOME):
            for name in ["ovcli.conf", "ovcli-reader.conf"]:
                value = load(root / "configs" / name).get("api_key")
                if value:
                    values.append(value)
    return [value for value in values if isinstance(value, str) and len(value) >= 8]


def redacted(value):
    secrets = secret_values()
    def scrub(item):
        if isinstance(item, dict):
            return {key: scrub(child) for key, child in item.items()}
        if isinstance(item, list):
            return [scrub(child) for child in item]
        if not isinstance(item, str):
            return item
        for secret in secrets:
            item = item.replace(secret, "[已隐藏]")
        item = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,})\b", "[已隐藏]", item)
        return re.sub(r"(?i)Bearer\s+[A-Za-z0-9_.+/=-]{16,}", "Bearer [已隐藏]", item)
    return scrub(value)


@app.middleware("http")
async def local_boundary(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        expected = str(request.base_url).rstrip("/")
        if (origin and origin != expected) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "请从本机看板访问"}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


def service_url():
    value = load(HOME / "configs/service.json").get("url", "http://127.0.0.1:1933")
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username or parsed.query or parsed.fragment:
        raise HTTPException(409, "服务地址须为本机 HTTP 地址")
    return value.rstrip("/")


def credential(code=None):
    if code:
        _, root = project(code)
        return load(root / "configs/ovcli.conf").get("api_key", "")
    try:
        return (HOME / "configs/root.key").read_text().strip()
    except OSError:
        return ""


async def native(client, path, code=None, authenticated=True):
    try:
        headers = {"Authorization": "Bearer " + credential(code)} if authenticated else {}
        response = await client.get(service_url() + path, headers=headers)
        if response.status_code != 200:
            return {"available": False, "error": f"服务返回 HTTP {response.status_code}"}
        data = response.json()
        if data.get("status") not in {"ok", "ready"}:
            return {"available": False, "error": "服务未确认成功"}
        return {"available": True, "data": data.get("result", data)}
    except (httpx.HTTPError, ValueError):
        return {"available": False, "error": "暂时无法连接本地 OpenViking 服务"}
    except HTTPException as error:
        return {"available": False, "error": str(error.detail)}


def source_state(code):
    entry, root = project(code)
    policy = load(root / "configs/pilot-policy.json", required=True)
    if not isinstance(policy.get("sources"), list) or not policy["sources"]:
        raise ValueError("项目白名单配置缺失")
    manifest_path = root / "evidence/source-manifest.json"
    receipt_path = root / "evidence/import-receipt.json"
    manifest = load(manifest_path, required=manifest_path.exists())
    receipt = load(receipt_path, required=receipt_path.exists())
    prior = {item["source_path"]: item for item in manifest.get("sources", [])}
    workspace = Path(policy.get("project", entry["workspace_roots"][0])).resolve()
    sources = []
    for spec in policy.get("sources", []):
        relative = Path(spec["path"])
        path = workspace / relative
        old = prior.get(str(path), {})
        status = "current"
        current_hash = None
        if relative.is_absolute() or ".." in relative.parts or path.is_symlink() or not path.resolve().is_relative_to(workspace):
            status = "blocked"
        elif not path.is_file():
            status = "missing"
        else:
            current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if current_hash != old.get("source_sha256"):
                status = "changed"
        sources.append({"id": old.get("source_id", spec.get("file", spec["path"])), "path": spec["path"], "file": old.get("curated_file", spec.get("file")), "role": spec["role"], "evidence_date": spec.get("evidence_date") or old.get("evidence_date"), "status": status, "sha256": current_hash, "indexed_sha256": old.get("source_sha256"), "selector": spec.get("selector", {})})
    last = load(root / "evidence/scheduled-sync-last.json")
    check = load(root / "evidence/mcp-check.json")
    changed = [item for item in sources if item["status"] != "current"]
    policy_paths = {str(workspace / spec["path"]) for spec in policy.get("sources", [])}
    selectors_changed = any(spec.get("selector") != prior.get(str(workspace / spec["path"]), {}).get("selector") for spec in policy.get("sources", []))
    rule_hash = hashlib.sha256(policy.get("source_policy_text", "").encode()).hexdigest()
    configuration_changed = bool(policy_paths != set(prior) or selectors_changed or rule_hash != receipt.get("fingerprints", {}).get("00-source-policy.md"))
    index_error = None
    directory = Path(manifest.get("curated_directory", root / "curated")).resolve()
    if not directory.is_relative_to(root) or manifest.get("snapshot_id") != receipt.get("snapshot_id"):
        index_error = "索引清单与回执不一致"
    else:
        for name, expected in receipt.get("fingerprints", {}).items():
            target = directory / name
            if Path(name).name != name or target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                index_error = "本地索引原文副本缺失或发生变化"
                break
    if last.get("status") == "running":
        index_error = None
    reference_changed = 0
    for name, expected in policy.get("reference_guards", {}).items():
        target = workspace / name
        if not target.resolve().is_relative_to(workspace) or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            reference_changed += 1
    verified = bool(check.get("passed") and check.get("snapshot_id") == receipt.get("snapshot_id") and not changed and not configuration_changed and not index_error and not reference_changed and last.get("status") != "running")
    return {"code": code, "name": entries().get(code, {}).get("name", code), "workspace": str(workspace), "account": entry["account"], "scope": entry["scope"], "validation": code == "setup-check", "sources": sources, "source_count": len(sources), "indexed_files": len(receipt.get("fingerprints", {})), "changed_count": len(changed), "configuration_changed": configuration_changed, "reference_changed_count": reference_changed, "index_error": index_error, "snapshot_id": receipt.get("snapshot_id"), "imported_at": receipt.get("imported_at"), "prepared_at": manifest.get("prepared_at"), "git_head": manifest.get("git_head"), "last_sync": last, "mcp_verified": verified, "mcp_checks": check.get("checks", {}), "native_codex_verified": check.get("native_codex_tool_call_verified", False)}


async def task_page(client, code, cursor="", query="", status="", limit=100):
    from urllib.parse import urlencode
    params = {"pagination": "cursor", "limit": limit}
    for key, value in [("cursor", cursor), ("q", query), ("status", status)]:
        if value:
            params[key] = value
    result = await native(client, "/api/v1/tasks?" + urlencode(params), code)
    if result["available"]:
        page = result["data"]
        page["items"] = [{"project": code, **{key: item.get(key) for key in ["task_id", "task_type", "status", "stage", "resource_id", "created_at", "updated_at", "processing_seconds", "error"]}} for item in page.get("items", [])]
    return result


async def live_project(client, code):
    try:
        local = await asyncio.to_thread(source_state, code)
    except (OSError, ValueError, KeyError, HTTPException):
        local = {"code": code, "name": entries().get(code, {}).get("name", code), "validation": code == "setup-check", "sources": [], "source_count": None, "indexed_files": None, "changed_count": None, "source_error": "本地项目资料状态无法读取", "mcp_verified": False}
    health, usage, models, vectors, tasks, activity = await asyncio.gather(
        native(client, "/health", code),
        native(client, "/api/v1/console/dashboard/summary?timezone=Asia%2FShanghai", code),
        native(client, "/api/v1/observer/models?format=json", code),
        native(client, "/api/v1/observer/vikingdb?format=json", code),
        task_page(client, code),
        asyncio.gather(*(task_page(client, code, status=status, limit=200) for status in ["pending", "running", "cancelling"])),
    )
    local.update(connection=health, usage=usage, models=models, vectors=vectors, tasks=tasks)
    local["activity"] = {"available": all(page["available"] for page in activity), "count": sum(len(page.get("data", {}).get("items", [])) for page in activity), "has_more": any(page.get("data", {}).get("has_more", False) for page in activity)}
    return local


def machine_state():
    pid_path = HOME / "server.pid"
    process = None
    try:
        pid = int(pid_path.read_text())
        output = subprocess.run(["ps", "-p", str(pid), "-o", "rss=,etime=,command="], capture_output=True, text=True, timeout=3).stdout.strip()
        fields = output.split(maxsplit=2)
        if len(fields) == 3 and str(HOME / "configs/ov.conf") in fields[2]:
            process = {"pid": pid, "memory_bytes": int(fields[0]) * 1024, "uptime": fields[1]}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    disk = shutil.disk_usage(HOME)
    return {"process": process, "disk_free_bytes": disk.free, "disk_total_bytes": disk.total}


@app.get("/api/overview")
async def overview():
    async with _cache_lock:
        if time.monotonic() - _cache.get("time", 0) < 4:
            return _cache["value"]
        async with httpx.AsyncClient(timeout=6, trust_env=False, follow_redirects=False) as client:
            health, ready, queue, projects = await asyncio.gather(
                native(client, "/health"), native(client, "/ready", authenticated=False),
                native(client, "/api/v1/observer/queue?format=json"),
                asyncio.gather(*(live_project(client, code) for code in entries())),
            )
        config = load(HOME / "configs/ov.conf")
        result = redacted({"checked_at": datetime.now(ZONE).isoformat(), "service_url": service_url(), "service": health, "ready": ready, "queue": queue, "projects": projects, "machine": machine_state(), "models": {"embedding": {key: config.get("embedding", {}).get("dense", {}).get(key) for key in ["provider", "model", "dimension", "api_base"]}, "summary": {key: config.get("vlm", {}).get(key) for key in ["provider", "model", "api_base", "max_concurrent"]}}, "schedule": load(HOME / "configs/scheduled-projects.json", {"enabled_projects": []})})
        _cache.update(time=time.monotonic(), value=result)
        return result


@app.get("/api/projects/{code}/tasks")
async def tasks(code: str, cursor: str = Query("", max_length=2048), q: str = Query("", max_length=200), status: str = ""):
    project(code)
    if status and status not in {"pending", "running", "cancelling", "completed", "failed", "cancelled"}:
        raise HTTPException(400, "无效的任务状态")
    async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
        return redacted(await task_page(client, code, cursor, q, status, 30))


@app.get("/api/tokens")
async def tokens(project_code: str = "all", include_validation: bool = False):
    codes = [code for code in entries() if include_validation or code != "setup-check"] if project_code == "all" else [project_code]
    for code in codes:
        project(code)
    today = datetime.now(ZONE).date()
    path = f"/api/v1/console/tokens?start_date={today - timedelta(days=6)}&end_date={today}&timezone=Asia%2FShanghai"
    async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
        results = await asyncio.gather(*(native(client, path, code) for code in codes))
    days = {}
    missing = []
    for code, result in zip(codes, results):
        if not result["available"] or result["data"].get("enabled") is False:
            missing.append(code)
            continue
        for item in result["data"].get("items", []):
            row = days.setdefault(item["date"], {"date": item["date"], "vlm_input": 0, "vlm_output": 0, "embedding_input": 0})
            for key in ["vlm_input", "vlm_output", "embedding_input"]:
                row[key] += item.get(key, 0)
    return {"items": sorted(days.values(), key=lambda item: item["date"]), "unavailable_projects": missing, "timezone": "Asia/Shanghai"}


@app.get("/api/projects/{code}/source/{source_id}")
async def source(code: str, source_id: str):
    try:
        item = source_state(code)
    except (OSError, ValueError, KeyError):
        raise HTTPException(409, "项目资料状态异常，请检查本机资料配置") from None
    found = next((entry for entry in item["sources"] if entry["id"] == source_id), None)
    if found is None:
        raise HTTPException(404, "资料不在项目白名单中")
    if found["status"] in {"blocked", "missing"}:
        raise HTTPException(409, "原文不可读取，请检查本地路径")
    path = Path(item["workspace"]) / found["path"]
    try:
        if path.stat().st_size > 1024 * 1024:
            raise HTTPException(413, "资料超过预览上限")
        sys.path.insert(0, str(HOME / "scripts"))
        from source_selection import select_text
        content, ranges = select_text(path.read_text(), found["selector"])
    except (OSError, ValueError, KeyError):
        raise HTTPException(409, "资料选区已变化或无法读取，请先复核白名单") from None
    return redacted({"source": found, "content": content, "line_ranges": ranges, "kind": "local_selected_source"})


class SearchInput(BaseModel):
    project_code: str
    query: str = Field(min_length=1, max_length=1000)

    @field_validator("query", mode="before")
    @classmethod
    def trim_query(cls, value):
        return value.strip() if isinstance(value, str) else value


async def worker(code, tool, arguments):
    project(code)
    proc = await asyncio.create_subprocess_exec(str(HOME / "venv/bin/python"), str(HOME / "scripts/router_worker.py"), code, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env={**os.environ, "OVK_HOME": str(HOME)})
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(json.dumps({"tool": tool, "arguments": arguments}).encode()), 28)
    except (TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise HTTPException(504, "检索超时，请检查本地服务") from None
    try:
        result = json.loads(stdout)
        if not result.get("ok"):
            raise HTTPException(409, redacted(result.get("error", "索引不可用，请检查资料新鲜度")))
        return json.loads(result["result"])
    except (ValueError, KeyError):
        raise HTTPException(502, "检索返回异常，请查看服务事件") from None


@app.post("/api/search")
async def search(body: SearchInput):
    return redacted(await worker(body.project_code, "find", {"query": body.query, "limit": 3}))


class ReadInput(BaseModel):
    project_code: str
    uri: str = Field(max_length=2000)
    snapshot_id: str = Field(max_length=128)
    offset: int = Field(default=0, ge=0)
    char_offset: int = Field(default=0, ge=0)


@app.post("/api/read")
async def read_index(body: ReadInput):
    return redacted(await worker(body.project_code, "read", {"uri": body.uri, "expected_snapshot": body.snapshot_id, "offset": body.offset, "char_offset": body.char_offset, "token_budget": 4000, "limit": 200}))


@app.get("/api/projects/{code}/preview")
async def preview(code: str):
    project(code)
    proc = await asyncio.create_subprocess_exec(str(HOME / "venv/bin/python"), str(HOME / "scripts/manage.py"), "project", "sync", code, "--dry-run", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env={**os.environ, "OVK_HOME": str(HOME)})
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), 25)
    except (TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise HTTPException(504, "同步预检超时") from None
    if proc.returncode:
        raise HTTPException(409, "预检未通过。可能有同步任务正在运行，请查看项目状态与事件。")
    try:
        return redacted(json.loads(stdout))
    except ValueError:
        raise HTTPException(502, "预检返回异常") from None


@app.get("/api/events")
async def events():
    result = []
    log = HOME / "logs/server.log"
    if log.exists():
        with log.open("rb") as stream:
            stream.seek(max(0, log.stat().st_size - 80000))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
        for line in lines[-500:]:
            if re.search(r"\b(ERROR|WARNING)\b", line):
                result.append({"level": "error" if "ERROR" in line else "warning", "message": line[:2000]})
    return redacted({"items": result[-80:][::-1], "source": "server.log", "note": "历史事件保留，当前健康状态以实时就绪检查为准。"})


@app.get("/health")
async def health():
    return {"status": "ok", "app": "openviking-local-dashboard", "instance": hashlib.sha256((str(HOME) + "\n" + str(Path(__file__).resolve().parent)).encode()).hexdigest()}


@app.get("/assets/{name}")
async def asset(name: str):
    if name not in {"app.js", "style.css", "favicon.svg"}:
        raise HTTPException(404)
    return FileResponse(STATIC / name)


@app.get("/")
@app.get("/studio/home")
async def index():
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    import uvicorn
    port = load(HOME / "dashboard/config.json").get("port", 1934)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Invalid dashboard port")
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)

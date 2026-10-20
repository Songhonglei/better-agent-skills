"""Single-writer, resumable synchronization with owned-resource removal."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from pilot_state import ROOT, SCOPE, SERVICE_ROOT, StateError, atomic_json, digest, fingerprint_id, load_policy, state_lock, writer_lock
from prepare_sources import build_snapshot, package_name, publish


def api(path, method="GET", root=ROOT):
    config = json.loads((root / "configs/ovcli.conf").read_text())
    request = Request(config["url"] + path, method=method,
                      headers={"Authorization": "Bearer " + config["api_key"]})
    with urlopen(request, timeout=10) as response:
        result = json.load(response)
    if result.get("status") != "ok":
        raise StateError("Local index operation failed.")
    return result["result"]


class LocalBackend:
    def __init__(self, root):
        self.root = root

    def tasks(self):
        return api("/api/v1/tasks", root=self.root)

    def task(self, task_id):
        return api("/api/v1/tasks/" + task_id, root=self.root)

    def stored_hash(self, scope, name):
        uri = scope + "/" + package_name(name)[:-3] + "/" + name
        try:
            content = api("/api/v1/content/read?" + urlencode({"uri": uri, "raw": "true"}), root=self.root)
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        return digest(content.encode()) if isinstance(content, str) else None

    def submit(self, path, target):
        environment = {**os.environ, "OPENVIKING_HOME": str(self.root),
                       "OPENVIKING_CLI_CONFIG_FILE": str(self.root / "configs/ovcli.conf")}
        options = load_policy(self.root).get("parser_args", {})
        with tempfile.TemporaryDirectory(prefix=".import-layout-", dir=self.root) as temporary:
            source = path
            if path.is_dir() and options.get("split_content") is False:
                # No-split directory parsing preserves input directories. Mirror the
                # canonical per-source layout used by incremental file imports.
                source = Path(temporary) / path.name
                source.mkdir()
                for entry in path.iterdir():
                    if entry.is_symlink() or not entry.is_file():
                        raise StateError("Unexpected entry in the immutable import corpus.")
                    name = package_name(entry.name)
                    folder = source / name[:-3]
                    folder.mkdir()
                    shutil.copyfile(entry, folder / name)
            arguments = [str(SERVICE_ROOT / "venv/bin/ov"), "add-resource", str(source), "--to", target,
                         "--include", "*.md", "-o", "json"]
            if options:
                arguments += ["--args", json.dumps(options)]
            result = subprocess.run(arguments, capture_output=True, text=True, env=environment, timeout=130)
        (self.root / "logs" / ("import-" + path.name + ".log")).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise StateError("Import outcome unknown; resume synchronization to query its journal.")
        data = json.loads(result.stdout)
        if not data.get("ok"):
            raise StateError("Import rejected; inspect its local response.")
        return self.task(data["result"]["task_id"])

    def remove(self, scope, name, expected):
        if scope != SCOPE:
            raise StateError("Refusing removal outside this pilot.")
        name = package_name(name)
        actual = self.stored_hash(scope, name)
        if actual is None:
            return
        if actual != expected:
            raise StateError("Owned resource changed outside sync; refusing removal.")
        target = scope + "/" + name[:-3]
        children = api("/api/v1/fs/ls?" + urlencode({"uri": target, "simple": "true", "node_limit": 1000}), root=self.root)
        if children != [target + "/" + name]:
            raise StateError("Resource contains unowned entries; refusing recursive removal.")
        api("/api/v1/fs?" + urlencode({"uri": target, "recursive": "true"}), method="DELETE", root=self.root)


def wait_for(backend, task):
    deadline = time.monotonic() + 600
    print(json.dumps({"task_id": task["task_id"], "status": task["status"]}), flush=True)
    while task["status"] not in {"completed", "failed", "cancelled"}:
        if time.monotonic() > deadline:
            raise StateError("Import still running; rerun sync to resume without resubmitting.")
        time.sleep(5)
        task = backend.task(task["task_id"])
    if task["status"] != "completed":
        raise StateError("An import failed; inspect its journal before any resubmission.")
    return task


def ensure_job(root, backend, journal, path, target, fingerprints, scope):
    key = target
    job_hash = fingerprint_id(fingerprints)
    entry = journal["jobs"].get(key)
    tasks = backend.tasks()
    active = [task for task in tasks if task.get("resource_id") == target and task["status"] not in {"completed", "failed", "cancelled"}]
    overlaps = [task for task in tasks if task["status"] not in {"completed", "failed", "cancelled"}
                and task.get("resource_id") != target and (target.startswith(task.get("resource_id", "!") + "/")
                or task.get("resource_id", "").startswith(target + "/"))]
    if overlaps:
        raise StateError("An overlapping parent or child import is active; wait before submitting.")
    if entry and entry["input_hash"] != job_hash and active:
        raise StateError("A different input snapshot is still importing.")
    if entry and entry["input_hash"] == job_hash:
        task_id = entry.get("task_id")
        if not task_id:
            candidates = [t for t in tasks if t.get("resource_id") == target and t["task_id"] not in entry["before_task_ids"]]
            if len(candidates) != 1:
                raise StateError("Import outcome unresolved; journal cannot identify exactly one submitted task.")
            task_id = entry["task_id"] = candidates[0]["task_id"]
            atomic_json(root / "evidence/sync-journal.json", journal)
        return wait_for(backend, backend.task(task_id))["task_id"]
    if active:
        raise StateError("An unjournaled import is active; inspect it before changing this target.")
    if all(backend.stored_hash(scope, name) == value for name, value in fingerprints.items()):
        return None
    entry = {"target": target, "input_hash": job_hash, "before_task_ids": [t["task_id"] for t in tasks], "outcome": "submitting"}
    journal["jobs"][key] = entry
    atomic_json(root / "evidence/sync-journal.json", journal)
    try:
        task = backend.submit(path, target)
    except Exception:
        entry["outcome"] = "unknown"
        atomic_json(root / "evidence/sync-journal.json", journal)
        raise
    entry.update(task_id=task["task_id"], outcome="submitted")
    atomic_json(root / "evidence/sync-journal.json", journal)
    return wait_for(backend, task)["task_id"]


def synchronize(root=ROOT, *, policy=None, backend=None, scan_key=None, dry_run=False, migrate_layout=False):
    with writer_lock(), state_lock(root, exclusive=True):
        policy = policy or load_policy(root)
        manifest, files, snapshots = build_snapshot(root, policy, scan_key)
        scope = manifest["target_uri"]
        receipt_path = root / "evidence/import-receipt.json"
        previous = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        if previous and previous.get("target_uri") != scope:
            raise StateError("Existing receipt belongs to a different resource scope.")
        if previous and previous.get("parser_args", {}) != policy.get("parser_args", {}):
            raise StateError("Parser options changed; review the indexed layout before synchronization.")
        old = previous.get("fingerprints", {})
        fingerprints = {name: digest(data) for name, data in sorted(files.items())}
        changed = [name for name, value in fingerprints.items() if old.get(name) != value]
        removed = [name for name in old if name not in fingerprints]
        migration = bool(old) and previous.get("schema_version", 1) < 2 and set(old) == set(fingerprints) and not removed
        plan = {"changed": changed, "removed": removed, "files": len(files), "snapshot_id": manifest["snapshot_id"],
                "layout_migration_eligible": migration, "requires_models": bool(changed)}
        if dry_run:
            return {"status": "dry-run", **plan, "model_calls": 0}
        if old and len(changed) + len(removed) > policy["max_changed_files"] and not (migration and migrate_layout):
            raise StateError("Change limit exceeded; only the reviewed schema-1 layout migration may bypass it.")
        publish(root, manifest, files, snapshots)
        if not changed and not removed and previous.get("status") == "complete":
            return {"status": "unchanged", "model_calls": 0, "audit_metadata_refreshed": True, "snapshot_id": manifest["snapshot_id"]}
        backend = backend or LocalBackend(root)
        journal_path = root / "evidence/sync-journal.json"
        journal = json.loads(journal_path.read_text()) if journal_path.exists() else {"jobs": {}}
        task_ids = []
        directory = Path(manifest["curated_directory"])
        if not old or (migration and migrate_layout):
            task = ensure_job(root, backend, journal, directory, scope, fingerprints, scope)
            if task:
                task_ids.append(task)
        else:
            for name in removed:
                backend.remove(scope, name, old[name])
            for name in changed:
                task = ensure_job(root, backend, journal, directory / name, scope + "/" + name[:-3], {name: fingerprints[name]}, scope)
                if task:
                    task_ids.append(task)
        for name, value in fingerprints.items():
            if backend.stored_hash(scope, name) != value:
                raise StateError("Indexed file differs from reviewed snapshot: " + name)
        if any(backend.stored_hash(scope, name) is not None for name in removed):
            raise StateError("An owned resource removal was not confirmed.")
        if any(digest(Path(s["source_path"]).read_bytes()) != s["source_sha256"] for s in manifest["sources"]):
            raise StateError("A source changed during import; resume with its latest snapshot.")
        receipt = {"schema_version": 2, "status": "complete", "task_ids": task_ids, "target_uri": scope,
                   "parser_args": policy.get("parser_args", {}),
                   "snapshot_id": fingerprint_id(fingerprints), "fingerprints": fingerprints,
                   "source_readbacks_verified": len(fingerprints),
                   "imported_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")}
        atomic_json(receipt_path, receipt)
        return {"status": "complete", "files": len(files), "source_readbacks_verified": len(files),
                "verified_import_tasks": len(task_ids), "removed": removed, "snapshot_id": receipt["snapshot_id"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--migrate-layout", action="store_true")
    args = parser.parse_args()
    print(json.dumps(synchronize(dry_run=args.dry_run, migrate_layout=args.migrate_layout), ensure_ascii=False))


if __name__ == "__main__":
    main()

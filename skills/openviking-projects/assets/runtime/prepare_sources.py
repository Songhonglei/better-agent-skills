"""Heading-selected corpus; audit metadata stays outside model input."""
import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from provider_runtime import secret_values
from source_selection import package_name, paragraphs, select_text
from pilot_state import ROOT, PROJECT_ID, StateError, atomic_json, check_reference_guards, curated_directory, digest, fingerprint_id, load_policy, state_lock

POLICY_NAME = "00-source-policy.md"
POLICY_TEXT = """# Project source rules

This is a selected local snapshot, not proof of live system state or action authorization.
Read source URIs and verify dates before relying on summaries. Prefer local read/rg for known paths.
Source manifests preserve original paths, hashes and selected ranges. Do not index secrets or raw business payloads.
"""


def git_metadata(directory, *arguments):
    """Git provenance is optional; source content hashes remain authoritative."""
    try:
        result = subprocess.run(["git", "-C", str(directory), "rev-parse", *arguments],
                                capture_output=True, text=True, timeout=3)
        return result.stdout.strip().splitlines() if result.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        return []


def build_snapshot(root=ROOT, policy=None, scan_key=None):
    policy = policy or load_policy(root)
    check_reference_guards(policy)
    project = Path(policy["project"]).resolve()
    old_path = root / "evidence/source-manifest.json"
    old = json.loads(old_path.read_text()) if old_path.exists() else {}
    old_sources = {s["source_path"]: s for s in old.get("sources", [])}
    catalog = dict(old.get("source_catalog", {}))
    catalog.update({str(Path(s["source_path"]).relative_to(project)): s["curated_file"]
                    for s in old.get("sources", []) if Path(s["source_path"]).is_relative_to(project)})
    if old:
        directory = curated_directory(root, old)
        owned = {s["curated_file"] for s in old["sources"]} | {POLICY_NAME}
        if {p.name for p in directory.iterdir()} != owned:
            raise StateError("Unexpected curated files; only previously owned packages may be removed.")
        for source in old["sources"]:
            if digest((directory / source["curated_file"]).read_bytes()) != source["curated_sha256"]:
                raise StateError("A prepared package was modified outside synchronization.")
        for name, fingerprint in old.get("fingerprints", {}).items():
            if digest((directory / package_name(name)).read_bytes()) != fingerprint:
                raise StateError("An immutable prepared package was modified.")
    if scan_key is None:
        scan_values = secret_values()
    else:
        scan_values = [scan_key]
    checked_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    head = git_metadata(project, "HEAD")
    manifest = {"schema_version": 2, "project": str(project), "git_head": head[0] if len(head) == 1 else None,
                "working_tree_snapshot": True, "prepared_at": checked_at, "preparation_uses_models": False,
                "target_uri": policy["scope"], "source_catalog": catalog, "sources": []}
    if policy.get("reference_guards"):
        manifest["reference_guards"] = dict(policy["reference_guards"])
    files = {POLICY_NAME: policy.get("source_policy_text", POLICY_TEXT).encode()}
    raw_snapshots, entry_ids = [], set()
    repository_cache, source_values, selected_values = {}, {}, {}
    for spec in policy["sources"]:
        relative = Path(spec["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise StateError("Source must be a project-relative path.")
        path = project / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(project):
            raise StateError("Missing or symlinked source: " + str(relative))
        data = path.read_bytes()
        text = data.decode("utf-8")
        if any(value and value in text for value in scan_values) or re.search(r"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|xoxb-[A-Za-z0-9-]{20,})\b|(?i:Bearer)\s+[A-Za-z0-9_\-./+=]{24,}", text):
            raise StateError("Credential scan requires review: " + str(relative))
        selected, ranges = select_text(text, spec["selector"])
        if spec.get("required_json"):
            value = json.loads(text)
            if any(key not in value or type(value[key]) is not type(expected) or value[key] != expected
                   for key, expected in spec["required_json"].items()):
                raise StateError("Source has not met its completed-evidence requirements: " + str(relative))
        source_values[str(relative)] = text
        selected_values[str(relative)] = selected
        evidence_date = spec.get("evidence_date")
        if spec.get("expected_work_id"):
            found = set(re.findall(r"workId(?:\s|固定为|为|[:：]|`)*(\d+)", selected, re.I))
            if found != {str(spec["expected_work_id"])}:
                raise StateError("Current project workId is missing or inconsistent: " + str(relative))
            entry_ids.update(found)
        if spec.get("entry_check"):
            entry_matches = set()
            selected_lines = selected.splitlines(keepends=True)
            for start, end in paragraphs(selected_lines):
                paragraph = "".join(selected_lines[start:end])
                match = re.search(r"workId\s*`?(\d+)", paragraph)
                if match and "跳转" in paragraph:
                    entry_matches.add(match[1])
            if len(entry_matches) != 1:
                raise StateError("Current entry lacks workId or legacy redirect boundary: " + str(relative))
            entry_ids.update(entry_matches)
            dates = []
            for value in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", selected):
                try:
                    dates.append(date.fromisoformat(value).isoformat())
                except ValueError:
                    pass
            evidence_date = max(dates) if dates else None
        name = package_name(catalog.get(str(relative), spec.get("file", "src-" + digest(str(relative))[:16] + ".md")))
        if name in files:
            raise StateError("Duplicate source package or source path.")
        catalog[str(relative)] = name
        files[name] = selected.encode()
        source_sha, selected_sha = digest(data), digest(files[name])
        prior = old_sources.get(str(path), {})
        parent = str(path.parent)
        if parent not in repository_cache:
            values = git_metadata(parent, "--show-toplevel", "HEAD")
            repository_cache[parent] = {"root": values[0], "head": values[1]} if len(values) == 2 else None
        snapshot = root / "evidence/source-snapshots" / source_sha / relative
        raw_snapshots.append((snapshot, data))
        manifest["sources"].append({"source_id": name[:-3], "source_path": str(path), "source_sha256": source_sha,
            "selected_sha256": selected_sha, "source_role": spec["role"], "priority": spec.get("priority", 50),
            "evidence_date": evidence_date, "snapshot_at": prior.get("snapshot_at", checked_at) if prior.get("source_sha256") == source_sha else checked_at,
            "source_line_ranges": ranges, "selector": spec["selector"], "live_state_verified": False,
            "source_snapshot_path": str(snapshot), "curated_file": name, "curated_sha256": selected_sha,
            "bytes": len(data), "curated_bytes": len(files[name]), "repository": repository_cache[parent]})
    if len(entry_ids) > 1:
        raise StateError("Current entry sources disagree on workId; resolve the source conflict before indexing.")
    for check in policy.get("consistency_checks", []):
        if check["json_source"] not in source_values or check["text_source"] not in selected_values:
            raise StateError("Consistency checks may only use whitelisted sources.")
        values = json.loads(source_values[check["json_source"]])
        target = selected_values[check["text_source"]]
        for template in check["required_templates"]:
            if template.format_map(values) not in target:
                raise StateError("Current status conflicts with its completed evidence; reconcile local sources before indexing.")
    fingerprints = {name: digest(data) for name, data in sorted(files.items())}
    manifest.update(snapshot_id=fingerprint_id(fingerprints), credential_scan="passed-selected-sources",
                    curated_file_count=len(files), curated_bytes=sum(map(len, files.values())),
                    current_work_id=next(iter(entry_ids), None), fingerprints=fingerprints)
    return manifest, files, raw_snapshots


def publish(root, manifest, files, raw_snapshots):
    generations = root / "prepared"
    generations.mkdir(exist_ok=True, mode=0o700)
    destination = generations / manifest["snapshot_id"]
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix=".staging-", dir=generations) as temporary:
            staging = Path(temporary) / "corpus"
            staging.mkdir(mode=0o700)
            for name, data in files.items():
                (staging / name).write_bytes(data)
            os.replace(staging, destination)
    if {p.name for p in destination.iterdir()} != set(files) or any((destination / n).read_bytes() != d for n, d in files.items()):
        raise StateError("An immutable prepared generation was modified.")
    for path, data in raw_snapshots:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.exists() and path.read_bytes() != data:
            raise StateError("An immutable raw source snapshot was modified.")
        if not path.exists():
            path.write_bytes(data)
    manifest["curated_directory"] = str(destination)
    current = root / ("curated/" + PROJECT_ID + "/current")
    current.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    old_directory = None
    if current.exists() and not current.is_symlink():
        old_directory = root / "evidence" / ("legacy-curated-" + uuid4().hex)
        os.replace(current, old_directory)
    link = current.with_name(".current-" + uuid4().hex)
    try:
        link.symlink_to(destination, target_is_directory=True)
        os.replace(link, current)
    except BaseException:
        link.unlink(missing_ok=True)
        if old_directory is not None and not current.exists():
            os.replace(old_directory, current)
        raise
    atomic_json(root / "evidence/source-manifest.json", manifest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with state_lock(exclusive=True):
        manifest, files, snapshots = build_snapshot()
        if not args.dry_run:
            publish(ROOT, manifest, files, snapshots)
    print(json.dumps({"status": "dry-run" if args.dry_run else "prepared", "files": len(files),
                      "snapshot_id": manifest["snapshot_id"], "curated_bytes": manifest["curated_bytes"]}))


if __name__ == "__main__":
    main()

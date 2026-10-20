"""Shared policy, atomic state publication and reader/writer coordination."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from project_profile import ROOT, SCOPE, SERVICE_ROOT, PROJECT_ID
from source_selection import validate_limits


class StateError(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def fingerprint_id(fingerprints):
    return digest(json.dumps(fingerprints, sort_keys=True, separators=(",", ":")))


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x") as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_policy(root=ROOT):
    value = json.loads((root / "configs/pilot-policy.json").read_text())
    if value["scope"] != SCOPE:
        raise StateError("This policy must remain within its selected project resource scope.")
    if value.get("parser_args", {}) not in ({}, {"split_content": False}):
        raise StateError("Only reviewed no-split parser options are permitted.")
    try:
        validate_limits(value)
    except ValueError as exc:
        raise StateError(str(exc)) from exc
    return value


def check_reference_guards(policy):
    project = Path(policy["project"]).resolve()
    for name, expected in policy.get("reference_guards", {}).items():
        relative = Path(name)
        path = project / relative
        if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                or not path.is_file() or not path.resolve().is_relative_to(project)
                or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
            raise StateError("Invalid verified-contract reference guard.")
        if digest(path.read_bytes()) != expected:
            raise StateError("Verified-contract implementation changed; reconcile the maintenance contract before indexing.")


@contextmanager
def state_lock(root=ROOT, *, exclusive=False):
    (root / "evidence").mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "evidence/sync.lock").open("a+") as stream:
        os.chmod(stream.name, 0o600)
        try:
            fcntl.flock(stream, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StateError("Pilot synchronization or a lookup is active; retry shortly.") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


@contextmanager
def writer_lock(root=SERVICE_ROOT):
    """Serialize imports across accounts sharing the local backend."""
    with state_lock(root / 'shared-writer', exclusive=True):
        yield


def curated_directory(root, manifest):
    directory = Path(manifest.get("curated_directory", root / ("curated/" + PROJECT_ID + "/current")))
    if not directory.resolve().is_relative_to(root.resolve()):
        raise StateError("Prepared corpus must remain inside this pilot.")
    return directory


def fresh_state(root=ROOT):
    manifest = json.loads((root / "evidence/source-manifest.json").read_text())
    check_reference_guards(manifest)
    receipt = json.loads((root / "evidence/import-receipt.json").read_text())
    if receipt.get("status") != "complete" or receipt.get("target_uri") != SCOPE:
        raise StateError("The reviewed index is not ready; use local files.")
    directory = curated_directory(root, manifest)
    expected = receipt["fingerprints"]
    if {p.name for p in directory.iterdir()} != set(expected):
        raise StateError("The reviewed corpus file set changed; use local files until sync completes.")
    for name, fingerprint in expected.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != fingerprint:
            raise StateError("The prepared and indexed snapshots differ; use local files.")
    for source in manifest["sources"]:
        path = Path(source["source_path"])
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != source["source_sha256"]:
            raise StateError("A source changed after indexing; refresh the snapshot or use local files.")
        if expected.get(source["curated_file"]) != source["curated_sha256"]:
            raise StateError("The prepared and indexed snapshots differ; use local files.")
    receipt["snapshot_id"] = fingerprint_id(expected)
    return manifest, receipt

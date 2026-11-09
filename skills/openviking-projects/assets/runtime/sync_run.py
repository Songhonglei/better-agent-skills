"""Durable sync receipts, owned subprocess cleanup and detached execution."""
import fcntl
import json
import os
import signal
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class SyncInterrupted(BaseException):
    def __init__(self, signum):
        self.signum = signum
        super().__init__("Synchronization interrupted; reconcile its journal before retrying.")


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def interrupt_signals():
    def stop(signum, frame):
        raise SyncInterrupted(signum)
    previous = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def archive(path, write):
    """Keep the exact previous receipt, including unfinished legacy runs."""
    if not path.exists():
        return None
    old = json.loads(path.read_text())
    history = path.parent / "sync-history"
    history.mkdir(exist_ok=True, mode=0o700)
    saved = history / (path.stem + "-" + uuid4().hex + ".json")
    with saved.open("xb") as stream:
        os.chmod(saved, 0o600)
        stream.write(path.read_bytes())
        stream.flush()
        os.fsync(stream.fileno())
    return {"run_id": old.get("run_id"), "status": old.get("status"), "receipt": str(saved)}


@contextmanager
def durable_run(path, initial, write, *, run_id=None):
    # The caller holds the run's lock before replacing any previous receipt.
    path = Path(path)
    previous = archive(path, write)
    record = {**initial, "status": "running", "pid": os.getpid(),
              "run_id": run_id or uuid4().hex, "started_at": timestamp()}
    if previous:
        record["previous_run"] = previous
    write(path, record)
    try:
        yield record
    except BaseException as exc:
        record.update(status="interrupted" if isinstance(exc, (SyncInterrupted, KeyboardInterrupt)) else "failed",
                      error_type=type(exc).__name__, recovery_required=True,
                      error="Sync did not finish; inspect its log and journal before retrying.")
        if isinstance(exc, SyncInterrupted):
            record["signal"] = exc.signum
        raise
    finally:
        if record["status"] == "running":
            record.update(status="interrupted", recovery_required=True,
                          error="Worker ended without a confirmed result; reconcile its journal.")
        record["finished_at"] = timestamp()
        write(path, record)


def run_logged(command, log_path, *, timeout, cwd=None, env=None):
    """Stream output immediately; terminate only this newly-created process group."""
    with Path(log_path).open("a+", buffering=1) as log:
        os.chmod(log_path, 0o600)
        log.write("\n" + timestamp() + "\n")
        log.flush()
        position = log.tell()
        child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = child.wait(timeout=timeout)
        finally:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child.wait(timeout=5)
        log.seek(position)
        lines = [line for line in log.read().splitlines() if line.strip()]
    return code, lines


def worker_alive(worker):
    """A saved PID alone never authorizes a signal or proves a worker is ours."""
    try:
        pid = worker["pid"]
        if type(pid) is not int or pid <= 1:
            return False
        result = subprocess.run(["ps", "-p", str(pid), "-o", "stat=", "-o", "command="],
                                capture_output=True, text=True, timeout=3)
        return (result.returncode == 0 and not result.stdout.lstrip().startswith("Z")
                and worker["command"][1] in result.stdout and os.getpgid(pid) == pid)
    except (KeyError, IndexError, OSError, subprocess.SubprocessError):
        return False


def sync_status(path, lock_path, write):
    """Reconcile SIGKILL/power-loss leftovers only when no worker owns the lock."""
    path, lock_path = Path(path), Path(lock_path)
    worker_path = path.with_suffix(".worker.json")
    worker = json.loads(worker_path.read_text()) if worker_path.exists() else {}
    current = json.loads(path.read_text()) if path.exists() else {"status": "not_started"}
    if worker and worker_alive(worker):
        if current.get("run_id") != worker["run_id"]:
            return {"status": "starting", "run_id": worker["run_id"], "pid": worker["pid"]}
        return current
    with lock_path.open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {**current, "status": "running", "lock_held": True}
        # Read again after acquiring the lock, avoiding a completed-worker race.
        current = json.loads(path.read_text()) if path.exists() else {"status": "not_started"}
        if current.get("status") == "running":
            saved = archive(path, write)
            current.update(status="interrupted", recovery_required=True, finished_at=timestamp(),
                           error="Worker is no longer running; reconcile its journal before retrying.",
                           interrupted_receipt=saved["receipt"])
            write(path, current)
    return current


def background(command, path, lock_path, write, *, cwd=None, env=None):
    """Start once in a new session; return its ID instead of waiting in the host chat."""
    path = Path(path)
    with path.with_suffix(".launch.lock").open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped", "reason": "already_running"}
        current = sync_status(path, lock_path, write)
        if current.get("status") in {"running", "starting"}:
            return {"status": "skipped", "reason": "already_running", "run_id": current.get("run_id")}
        run_id = uuid4().hex
        log_path = path.parent.parent / "logs/sync-background.log"
        with log_path.open("ab", buffering=0) as log:
            os.chmod(log_path, 0o600)
            child = subprocess.Popen(command, cwd=cwd,
                env={**(os.environ if env is None else env), "OVK_SYNC_RUN_ID": run_id, "PYTHONUNBUFFERED": "1"},
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        worker = {"run_id": run_id, "pid": child.pid, "command": list(command), "started_at": timestamp()}
        write(path.with_suffix(".worker.json"), worker)
        # A short bounded handshake detects immediate startup failure; do not
        # report a receipt from a previous run as this worker's success.
        for _ in range(100):
            if path.exists() and json.loads(path.read_text()).get("run_id") == run_id:
                return {"status": "started", "run_id": run_id, "pid": child.pid, "receipt": str(path)}
            if child.poll() is not None:
                raise RuntimeError("Sync worker exited before starting; inspect sync-background.log.")
            time.sleep(0.05)
        return {"status": "starting", "run_id": run_id, "pid": child.pid, "receipt": str(path)}

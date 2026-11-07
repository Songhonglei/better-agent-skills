"""Start the local dashboard and install its reversible Studio entry point."""
import argparse
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
STATE = Path(os.environ.get("OVK_HOME", str(Path.home() / ".openviking-projects"))).resolve()
RUNTIME = STATE / "dashboard"
PID = RUNTIME / "server.pid"
CONFIG = json.loads((RUNTIME / "config.json").read_text()) if (RUNTIME / "config.json").exists() else {}
PORT = CONFIG.get("port", 1934)
if type(PORT) is not int or not 1024 <= PORT <= 65535:
    raise ValueError("Invalid dashboard port")
URL = f"http://127.0.0.1:{PORT}"
INSTANCE = hashlib.sha256((str(STATE) + "\n" + str(ROOT)).encode()).hexdigest()


def studio_url():
    from urllib.parse import urlsplit
    value = json.loads((STATE / "configs/service.json").read_text()).get("url", "")
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("Studio requires a configured local HTTP service")
    return value.rstrip("/") + "/studio/home"


def atomic_write(path, content, mode=0o600):
    descriptor, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def response():
    try:
        with build_opener(ProxyHandler({})).open(URL + "/health", timeout=2) as stream:
            value = json.load(stream)
            return value.get("app") == "openviking-local-dashboard" and value.get("instance") == INSTANCE
    except (OSError, ValueError):
        return False


def owned(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=3)
    return str(ROOT / "server.py") in result.stdout


def start():
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUNTIME.chmod(0o700)
    if PID.exists() and owned(int(PID.read_text())) and response():
        return {"status": "already_running", "url": URL}
    import socket
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError("Dashboard port is occupied by another instance. Inspect it or choose another port.")
    python = STATE / "venv/bin/python"
    with (RUNTIME / "server.log").open("a") as log:
        process = subprocess.Popen([str(python), str(ROOT / "server.py")], cwd=ROOT, env={**os.environ, "OVK_HOME": str(STATE)}, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    atomic_write(PID, (str(process.pid) + "\n").encode())
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError("Dashboard exited during startup. Inspect its local log.")
        if response():
            return {"status": "running", "url": URL, "pid": process.pid}
        time.sleep(0.2)
    if owned(process.pid):
        process.terminate()
        process.wait(timeout=10)
    raise RuntimeError("Dashboard did not become ready.")


def stop():
    if not PID.exists():
        return {"status": "not_running"}
    pid = int(PID.read_text())
    if not owned(pid):
        raise RuntimeError("PID ownership could not be confirmed. No signal was sent.")
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not owned(pid):
            PID.unlink(missing_ok=True)
            return {"status": "stopped"}
        time.sleep(0.1)
    raise RuntimeError("Dashboard is still shutting down.")


def studio_dir():
    import importlib.util
    package = importlib.util.find_spec("openviking")
    if not package or not package.origin:
        raise RuntimeError("Use the existing OpenViking Python environment.")
    return Path(package.origin).parent / "web_studio/dist"


def install_entry():
    if not response():
        raise RuntimeError("Start and verify the dashboard before changing the Studio entry.")
    entry_url = studio_url()
    directory = studio_dir()
    index = directory / "index.html"
    backup = RUNTIME / "studio-original.html"
    receipt_path = RUNTIME / "studio-entry.json"
    old = index.read_bytes()
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    if receipt and hashlib.sha256(old).hexdigest() == receipt["installed_sha256"]:
        return {"status": "already_installed", "url": entry_url}
    if receipt:
        raise RuntimeError("Studio contents changed. Review the saved receipt before replacing it.")
    if any((directory / name).exists() for name in ["classic.html", "local-entry.js"]):
        raise RuntimeError("Studio already contains a classic or local entry file. Review it before replacing it.")
    if backup.exists() and backup.read_bytes() != old:
        raise RuntimeError("An existing Studio backup differs. Review it before continuing.")
    atomic_write(backup, old)
    atomic_write(directory / "classic.html", old, 0o644)
    script = ('"use strict";\nif (new URLSearchParams(location.search).get("view") === "classic") {\n'
              '  fetch("/studio/classic.html", {cache:"no-store"}).then(response => response.text()).then(html => { document.open(); document.write(html); document.close(); });\n'
              '} else {\n  location.replace(' + json.dumps(URL + "/") + ' + location.hash);\n}\n')
    atomic_write(directory / "local-entry.js", script.encode(), 0o644)
    installed = ('''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenViking 本地监控</title>
<script src="/studio/local-entry.js" defer></script>
</head>
<body><p>正在打开本地看板…</p><p><a href="__DASHBOARD_URL__/">打开本地看板</a></p></body>
</html>'''.replace('__DASHBOARD_URL__', URL)).encode()
    receipt = {"entry": str(index), "original_sha256": hashlib.sha256(old).hexdigest(), "installed_sha256": hashlib.sha256(installed).hexdigest(), "backup": str(backup), "dashboard_url": URL}
    atomic_write(receipt_path, (json.dumps(receipt, indent=2) + "\n").encode())
    atomic_write(index, installed, 0o644)
    return {"status": "installed", "url": entry_url, "classic_url": entry_url + "?view=classic"}


def restore_entry():
    receipt_path = RUNTIME / "studio-entry.json"
    if not receipt_path.exists():
        return {"status": "not_installed"}
    receipt = json.loads(receipt_path.read_text())
    index = Path(receipt["entry"])
    backup = Path(receipt["backup"])
    current_hash = hashlib.sha256(index.read_bytes()).hexdigest()
    if current_hash not in {receipt["installed_sha256"], receipt["original_sha256"]}:
        raise RuntimeError("The installed entry was edited. Refusing to overwrite it.")
    if hashlib.sha256(backup.read_bytes()).hexdigest() != receipt["original_sha256"]:
        raise RuntimeError("The original entry backup no longer matches its receipt.")
    atomic_write(index, backup.read_bytes(), 0o644)
    stamp = time.time_ns()
    receipt_path.rename(RUNTIME / f"studio-entry-restored-{stamp}.json")
    backup.rename(RUNTIME / f"studio-original-restored-{stamp}.html")
    for name in ["classic.html", "local-entry.js"]:
        (index.parent / name).unlink(missing_ok=True)
    return {"status": "restored"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "stop", "status", "install-entry", "restore-entry"])
    args = parser.parse_args()
    try:
        actions = {"start": start, "stop": stop, "install-entry": install_entry, "restore-entry": restore_entry, "status": lambda: {"ready": response(), "url": URL}}
        RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (RUNTIME / "control.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            print(json.dumps(actions[args.command](), ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        raise SystemExit(1)

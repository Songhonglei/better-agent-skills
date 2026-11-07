#!/usr/bin/env python3
"""Opt-in dashboard deployment; never started by ordinary runtime installation."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ovk import SKILL, interpreter, state_root, write_json


def install(root, port=None, dry_run=False):
    assets = SKILL / 'assets/dashboard'
    sources = sorted(path for path in assets.rglob('*') if path.is_file()
                     and '__pycache__' not in path.parts and path.suffix != '.pyc')
    manifest = {str(path.relative_to(assets)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    target = root / 'dashboard/app'
    receipt = root / 'dashboard/app-manifest.json'
    config = root / 'dashboard/config.json'
    if not sources:
        raise ValueError('Dashboard assets are missing.')
    existing = json.loads(config.read_text()) if config.exists() else {}
    port = port if port is not None else existing.get('port', 1934)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Choose an unprivileged dashboard port between 1024 and 65535.')
    if existing and existing.get('port') != port:
        raise ValueError('Dashboard is already configured on another port; stop it and review its config before changing ports.')
    if target.exists():
        if not receipt.exists() or json.loads(receipt.read_text()) != manifest:
            raise ValueError('Existing dashboard differs. Preserve it and review an explicit upgrade before replacing it.')
        actual = {str(path.relative_to(target)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in target.rglob('*') if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}
        if actual != manifest:
            raise ValueError('Installed dashboard was locally changed; refusing to overwrite it.')
    plan = {'status': 'planned', 'target': str(target), 'url': f'http://127.0.0.1:{port}',
            'files': len(manifest), 'starts_service': False, 'replaces_studio_entry': False}
    if dry_run:
        return plan
    if not (root / 'configs/runtime-manifest.json').is_file() or not interpreter(root).is_file():
        raise ValueError('Install the project runtime first; dashboard installation does not initialize another service.')
    check = subprocess.run([str(interpreter(root)), '-c',
        'import fastapi,httpx,uvicorn,pydantic,importlib.metadata;'
        'assert importlib.metadata.version("openviking")=="0.5.0";'
        'assert int(pydantic.__version__.split(".")[0])>=2'], capture_output=True, timeout=20)
    if check.returncode:
        raise RuntimeError('The existing venv needs OpenViking 0.5.0 with FastAPI, httpx, uvicorn and Pydantic 2; inspect its dependencies before proceeding.')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix='.app-', dir=target.parent) as temporary:
            staged = Path(temporary) / 'app'
            for source in sources:
                output = staged / source.relative_to(assets)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, output)
                output.chmod(0o600)
            staged.rename(target)
    write_json(receipt, manifest)
    write_json(config, {'port': port})
    return {**plan, 'status': 'installed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', default=os.environ.get('OVK_HOME', str(Path.home() / '.openviking-projects')))
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('install')
    command.add_argument('--port', type=int)
    command.add_argument('--dry-run', action='store_true')
    for name in ['start', 'stop', 'status', 'install-entry', 'restore-entry']:
        sub.add_parser(name)
    args = parser.parse_args()
    root = state_root(args.home)
    if args.command == 'install':
        print(json.dumps(install(root, args.port, args.dry_run), ensure_ascii=False, indent=2))
        return 0
    manager = root / 'dashboard/app/manage.py'
    if not manager.is_file() or not interpreter(root).is_file():
        raise ValueError('Install the optional dashboard first: studio install.')
    return subprocess.call([str(interpreter(root)), str(manager), args.command], env={**os.environ, 'OVK_HOME': str(root)})


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)

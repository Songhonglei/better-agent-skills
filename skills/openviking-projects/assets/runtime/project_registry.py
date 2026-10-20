"""One trusted local registry for legacy sync profiles and the shared MCP router."""
import json
import os
import re
import subprocess
from pathlib import Path

SERVICE_ROOT = Path(os.environ.get('OVK_HOME', str(Path.home() / '.openviking-projects'))).expanduser().resolve()
REGISTRY_PATH = SERVICE_ROOT / 'configs/projects.json'


def load_registry():
    value = json.loads(REGISTRY_PATH.read_text())
    if value.get('schema_version') != 1 or not isinstance(value.get('projects'), dict):
        raise ValueError('Invalid project registry schema.')
    result = value['projects']
    for code, entry in result.items():
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', code):
            raise ValueError('Invalid registered project code.')
        root = Path(entry['data_root'])
        if not root.is_absolute() or not root.resolve().is_relative_to(SERVICE_ROOT.resolve()):
            raise ValueError('Project state must be inside the local service directory.')
        if entry['scope'] != 'viking://resources/projects/' + code + '/current':
            raise ValueError('Project scope does not match its code.')
        roots = entry['workspace_roots']
        if not isinstance(roots, list) or not roots or any(not Path(p).is_absolute() for p in roots):
            raise ValueError('Register absolute workspace roots.')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', entry['account']):
            raise ValueError('Invalid registered account.')
    return result


def project_entry(code):
    if not isinstance(code, str) or code not in (entries := load_registry()):
        raise ValueError('Unknown project_code; register the project before using OpenViking.')
    return entries[code]


def git_common(path):
    try:
        result = subprocess.run(['git', '-C', str(path), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                                capture_output=True, text=True, timeout=3)
        return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def resolve_workspace(workspace_path):
    path = Path(workspace_path).expanduser()
    if not path.is_absolute():
        raise ValueError('workspace_path must be an absolute local directory.')
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError('workspace_path must be a directory.')
    entries = load_registry()
    candidates = []
    for code, entry in entries.items():
        for name in entry['workspace_roots']:
            root = Path(name).resolve()
            if path.is_relative_to(root):
                candidates.append((len(root.parts), code))
    if candidates:
        depth = max(item[0] for item in candidates)
        codes = {code for length, code in candidates if length == depth}
    else:
        common = git_common(path)
        codes = {code for code, entry in entries.items()
                 if common and any(git_common(Path(p)) == common for p in entry['workspace_roots'])}
    if len(codes) != 1:
        raise ValueError('Workspace is unregistered or ambiguous; register an explicit root or clone alias.')
    code = codes.pop()
    return {'project_code': code, 'workspace_path': str(path), 'scope': entries[code]['scope']}


def validate_workspace(code, workspace_path):
    entry = project_entry(code)
    if resolve_workspace(workspace_path)['project_code'] != code:
        raise ValueError('project_code does not match workspace_path.')
    return entry

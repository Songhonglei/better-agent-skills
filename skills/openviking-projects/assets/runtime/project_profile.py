"""Explicit local profiles; never derive an account or scope from a caller URI."""
import os
from pathlib import Path
from project_registry import SERVICE_ROOT, load_registry

ENTRIES = load_registry()
PROFILES = {code: (Path(entry['data_root']), entry['account']) for code, entry in ENTRIES.items()}
PROJECT_ID = os.environ.get('OVK_PROJECT', '')
if PROJECT_ID not in PROFILES:
    raise RuntimeError('Unknown OpenViking project profile.')
ROOT, ACCOUNT = PROFILES[PROJECT_ID]
SCOPE = ENTRIES[PROJECT_ID]['scope']

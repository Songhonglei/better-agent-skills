#!/usr/bin/env python3
"""
claw-memory-manager: OpenClaw Agent memory feature manager.

Supports: check / enable / disable / status
Features:
  - dreaming  : Light→REM→Deep memory consolidation (auto-promote high-recall
                signals to long-term MEMORY.md)
  - (extensible) future features like active-memory can be added to the
    FEATURES dict below

Usage:
  python3 agent_memory.py status dreaming
  python3 agent_memory.py check dreaming
  python3 agent_memory.py enable dreaming
  python3 agent_memory.py enable dreaming --half-life 30 --max-age 60
  python3 agent_memory.py enable dreaming --timezone America/New_York
  python3 agent_memory.py enable dreaming --dry-run
  python3 agent_memory.py enable dreaming --backup
  python3 agent_memory.py disable dreaming

Safe defaults:
  - Backup: create *.bak.<timestamp> before any write (use --no-backup to skip)
  - Dry-run: --dry-run prints planned changes without writing
  - Container path sync: auto-detect /app/clawconfig/ and similar paths,
    skip silently if absent (for non-K8s installs)
  - Gateway restart: enable/disable auto-runs `openclaw gateway restart` to
    apply changes (use --no-restart to skip)
  - Timezone: defaults to UTC; override with --timezone <Area/City>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ----- Paths -----
RUNTIME_CONFIG = Path(
    os.environ.get(
        "OPENCLAW_CONFIG",
        str(Path.home() / ".openclaw" / "openclaw.json"),
    )
)

# Optional managed-environment sync targets (K8s ConfigMap mirrors etc.)
# Auto-detected at runtime — silently skipped if absent.
CONTAINER_SYNC_TARGETS = [
    Path("/app/clawconfig/openclaw.json"),
    Path("/app/k8s-config/clawconfig/openclaw.json"),
]

# ----- Defaults -----
DEFAULT_HALF_LIFE_DAYS = 30
MAX_HALF_LIFE_DAYS = 90
DEFAULT_MAX_AGE_DAYS = 60
MAX_ALLOWED_AGE_DAYS = 90
DEFAULT_TIMEZONE = "UTC"  # International default; override with --timezone


# ----- Feature registry -----
FEATURES = {
    "dreaming": {
        "path": ["plugins", "entries", "memory-core", "config", "dreaming"],
        "enable_patch": {
            "enabled": True,
            "frequency": "0 3 * * *",
        },
        "disable_patch": {"enabled": False},
        "check_key": "enabled",
        "status_key": "frequency",
        "description": (
            "Memory consolidation (Light→REM→Deep three-phase auto-promotion "
            "at 03:00 daily); promotes high-recall signals to long-term MEMORY.md"
        ),
        "supports_timezone": True,
        "supports_half_life": True,
        "supports_max_age": True,
    },
    # Reserved slot for future active-memory feature; uncomment when ready:
    # "active-memory": {
    #     "path": ["plugins", "entries", "active-memory", "config"],
    #     "enable_patch": {"enabled": True},
    #     "disable_patch": {"enabled": False},
    #     "check_key": "enabled",
    #     "status_key": None,
    #     "description": "Proactive memory injection into agent context window",
    # },
}


# ----- IO -----
def load_config(path: Path) -> dict:
    if not path.exists():
        print(f"❌ Config file does not exist: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Config file parse failed: {path}\n   {e}", file=sys.stderr)
        sys.exit(1)


def save_config(cfg: dict, path: Path) -> None:
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def backup_config(path: Path) -> Path | None:
    if not path.exists():
        return None
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = path.with_name(f"{path.name}.bak.{ts}")
    shutil.copy2(path, bak)
    return bak


# ----- Nested dict ops -----
def get_nested(cfg: dict, keys: list):
    node = cfg
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node


def set_nested(cfg: dict, keys: list, patch: dict) -> None:
    node = cfg
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    last = keys[-1]
    if last not in node or not isinstance(node[last], dict):
        node[last] = {}
    node[last].update(patch)


# ----- Side-effects -----
def sync_to_managed_targets(cfg: dict, dry_run: bool = False) -> list[str]:
    """Sync to managed-environment mirrors (K8s ConfigMap etc.) IF they exist.

    Returns list of paths actually synced (or would-be-synced under dry-run).
    """
    synced = []
    for dest in CONTAINER_SYNC_TARGETS:
        if dest.parent.exists():
            if dry_run:
                synced.append(f"{dest} (DRY-RUN)")
            else:
                try:
                    save_config(cfg, dest)
                    synced.append(str(dest))
                except PermissionError:
                    print(f"  ⚠️  Sync to {dest} skipped: permission denied", file=sys.stderr)
                except Exception as e:
                    print(f"  ⚠️  Sync to {dest} failed: {e}", file=sys.stderr)
    return synced


def reload_gateway(dry_run: bool = False) -> bool:
    """Trigger `openclaw gateway restart` to apply config changes."""
    if dry_run:
        print("   📋 [DRY-RUN] Would run: openclaw gateway restart")
        return True
    try:
        result = subprocess.run(
            ["openclaw", "gateway", "restart"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except FileNotFoundError:
        print("   ⚠️  `openclaw` CLI not found in PATH; skipping restart", file=sys.stderr)
        return False
    except Exception as e:
        print(f"   ⚠️  Gateway restart failed: {e}", file=sys.stderr)
        return False


def check_version() -> str:
    try:
        r = subprocess.run(
            ["openclaw", "--version"], capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown (openclaw CLI not in PATH)"


# ----- Commands -----
def cmd_status(feature_name: str) -> None:
    feat = FEATURES.get(feature_name)
    if not feat:
        print(f"❌ Unknown feature: {feature_name}; supported: {', '.join(FEATURES)}")
        sys.exit(1)

    cfg = load_config(RUNTIME_CONFIG)
    current = get_nested(cfg, feat["path"])
    version = check_version()

    print(f"\n📋 Feature: {feature_name}")
    print(f"   Description: {feat['description']}")
    print(f"   OpenClaw:    {version}")
    print(f"   Config:      {RUNTIME_CONFIG}")
    if current is None:
        print("   Status:      not configured")
    else:
        enabled = current.get("enabled", False)
        print(f"   Status:      {'✅ enabled' if enabled else '❌ disabled'}")
        if enabled and feat.get("status_key") and feat["status_key"] in current:
            print(f"   Schedule:    {current[feat['status_key']]}")
            tz = current.get("timezone", DEFAULT_TIMEZONE)
            print(f"   Timezone:    {tz}")
        if feature_name == "dreaming":
            deep = get_nested(cfg, feat["path"] + ["phases", "deep"])
            hl = deep.get("recencyHalfLifeDays", DEFAULT_HALF_LIFE_DAYS) if deep else DEFAULT_HALF_LIFE_DAYS
            ma = deep.get("maxAgeDays", DEFAULT_MAX_AGE_DAYS) if deep else DEFAULT_MAX_AGE_DAYS
            print(f"   Half-life:   {hl} days (--half-life 1-{MAX_HALF_LIFE_DAYS})")
            print(f"   Max-age:     {ma} days (--max-age 1-{MAX_ALLOWED_AGE_DAYS})")
        print(f"   Full config: {json.dumps(current, ensure_ascii=False)}")


def cmd_check(feature_name: str) -> None:
    feat = FEATURES.get(feature_name)
    if not feat:
        print(f"❌ Unknown feature: {feature_name}")
        sys.exit(1)
    version = check_version()
    print(f"\n🔍 Checking support for {feature_name}")
    print(f"   OpenClaw version: {version}")
    try:
        r = subprocess.run(
            ["openclaw", "config", "schema.lookup", ".".join(feat["path"])],
            capture_output=True, text=True, timeout=10,
        )
        print(f"   Schema:           {'✅ exists' if r.returncode == 0 else '⚠️ lookup failed (may be unsupported on this version)'}")
    except FileNotFoundError:
        print(f"   Schema:           ⚠️ openclaw CLI not in PATH")
    except Exception:
        print(f"   Schema:           ⚠️ unable to query")
    cfg = load_config(RUNTIME_CONFIG)
    current = get_nested(cfg, feat["path"])
    enabled = current.get("enabled", False) if current else False
    print(f"   Current state:    {'enabled' if enabled else 'not enabled'}")
    print(f"\n   To enable: python3 agent_memory.py enable {feature_name}")


def cmd_enable(
    feature_name: str,
    half_life_days: int | None = None,
    max_age_days: int | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    dry_run: bool = False,
    backup: bool = True,
    restart: bool = True,
) -> None:
    feat = FEATURES.get(feature_name)
    if not feat:
        print(f"❌ Unknown feature: {feature_name}")
        sys.exit(1)

    # Validate dreaming-specific args
    if half_life_days is not None:
        if not feat.get("supports_half_life"):
            print(f"⚠️  --half-life not supported for {feature_name}; ignored")
            half_life_days = None
        elif not (1 <= half_life_days <= MAX_HALF_LIFE_DAYS):
            print(f"❌ --half-life must be 1-{MAX_HALF_LIFE_DAYS} days, got: {half_life_days}")
            sys.exit(1)
    if max_age_days is not None:
        if not feat.get("supports_max_age"):
            print(f"⚠️  --max-age not supported for {feature_name}; ignored")
            max_age_days = None
        elif not (1 <= max_age_days <= MAX_ALLOWED_AGE_DAYS):
            print(f"❌ --max-age must be 1-{MAX_ALLOWED_AGE_DAYS} days, got: {max_age_days}")
            sys.exit(1)

    print(f"\n🔧 Enabling {feature_name}{' [DRY-RUN]' if dry_run else ''}...")

    cfg = load_config(RUNTIME_CONFIG)

    # Apply enable patch + (optional) timezone
    enable_patch = dict(feat["enable_patch"])
    if feat.get("supports_timezone"):
        enable_patch["timezone"] = timezone
    set_nested(cfg, feat["path"], enable_patch)

    # dreaming-specific deep-phase config
    if feature_name == "dreaming":
        hl = half_life_days if half_life_days is not None else DEFAULT_HALF_LIFE_DAYS
        ma = max_age_days if max_age_days is not None else DEFAULT_MAX_AGE_DAYS
        set_nested(cfg, feat["path"] + ["phases", "deep"], {
            "recencyHalfLifeDays": hl,
            "maxAgeDays": ma,
        })
        print(f"   Half-life:  {hl} days{' (default)' if half_life_days is None else ''}")
        print(f"   Max-age:    {ma} days{' (default)' if max_age_days is None else ''}")
        print(f"   Timezone:   {timezone}")

    if dry_run:
        print("\n📋 [DRY-RUN] Would write:")
        new_section = get_nested(cfg, feat["path"])
        print(json.dumps(new_section, indent=2, ensure_ascii=False))
        print(f"\n   Target: {RUNTIME_CONFIG}")
        sync_to_managed_targets(cfg, dry_run=True)
        if restart:
            reload_gateway(dry_run=True)
        print("\n💡 Re-run without --dry-run to apply.")
        return

    # Backup before write
    if backup:
        bak = backup_config(RUNTIME_CONFIG)
        if bak:
            print(f"   📦 Backup: {bak}")

    # Write runtime config
    save_config(cfg, RUNTIME_CONFIG)
    print(f"   ✅ Wrote {RUNTIME_CONFIG}")

    # Sync to managed targets (no-op if not present)
    synced = sync_to_managed_targets(cfg)
    for s in synced:
        print(f"   ✅ Synced to {s}")

    # Restart gateway to apply
    if restart:
        if reload_gateway():
            print("   ✅ Gateway restarted")
        else:
            print("   ⚠️  Gateway restart failed; manually run: openclaw gateway restart")
    else:
        print("   ⏭️  Skipping gateway restart (--no-restart); changes will apply on next restart")

    # Verify
    cfg_verify = load_config(RUNTIME_CONFIG)
    current = get_nested(cfg_verify, feat["path"])
    if current and current.get("enabled"):
        print(f"\n✅ {feature_name} successfully enabled")
        if feat.get("status_key") and feat["status_key"] in current:
            print(f"   Schedule: {current[feat['status_key']]}")
    else:
        print(f"\n❌ Verification failed; please inspect config manually")
        sys.exit(1)


def cmd_disable(
    feature_name: str,
    dry_run: bool = False,
    backup: bool = True,
    restart: bool = True,
) -> None:
    feat = FEATURES.get(feature_name)
    if not feat:
        print(f"❌ Unknown feature: {feature_name}")
        sys.exit(1)

    print(f"\n🔧 Disabling {feature_name}{' [DRY-RUN]' if dry_run else ''}...")
    cfg = load_config(RUNTIME_CONFIG)
    set_nested(cfg, feat["path"], feat["disable_patch"])

    if dry_run:
        new_section = get_nested(cfg, feat["path"])
        print(f"\n📋 [DRY-RUN] Would set: {json.dumps(new_section, ensure_ascii=False)}")
        sync_to_managed_targets(cfg, dry_run=True)
        if restart:
            reload_gateway(dry_run=True)
        print("\n💡 Re-run without --dry-run to apply.")
        return

    if backup:
        bak = backup_config(RUNTIME_CONFIG)
        if bak:
            print(f"   📦 Backup: {bak}")

    save_config(cfg, RUNTIME_CONFIG)
    synced = sync_to_managed_targets(cfg)
    for s in synced:
        print(f"   ✅ Synced to {s}")
    if restart:
        if reload_gateway():
            print("   ✅ Gateway restarted")
        else:
            print("   ⚠️  Gateway restart failed; manually run: openclaw gateway restart")
    print(f"\n✅ {feature_name} disabled")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agent_memory.py",
        description="claw-memory-manager: OpenClaw Agent memory feature manager",
    )
    parser.add_argument("action", choices=["check", "enable", "disable", "status"])
    parser.add_argument("feature", choices=list(FEATURES.keys()),
                        help=f"Memory feature: {', '.join(FEATURES)}")
    parser.add_argument("--half-life", type=int, dest="half_life",
                        help=f"Signal half-life days (dreaming only, 1-{MAX_HALF_LIFE_DAYS})")
    parser.add_argument("--max-age", type=int, dest="max_age",
                        help=f"Signal max-age days (dreaming only, 1-{MAX_ALLOWED_AGE_DAYS})")
    parser.add_argument("--timezone", type=str, default=DEFAULT_TIMEZONE,
                        help=f"IANA timezone for dreaming schedule (default: {DEFAULT_TIMEZONE}; e.g. America/New_York, Asia/Tokyo)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned changes without writing")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip creating *.bak.<timestamp> before write")
    parser.add_argument("--no-restart", action="store_true",
                        help="Skip `openclaw gateway restart` after change")
    args = parser.parse_args()

    if args.action == "enable":
        cmd_enable(
            args.feature,
            half_life_days=args.half_life,
            max_age_days=args.max_age,
            timezone=args.timezone,
            dry_run=args.dry_run,
            backup=not args.no_backup,
            restart=not args.no_restart,
        )
    elif args.action == "check":
        cmd_check(args.feature)
    elif args.action == "disable":
        cmd_disable(
            args.feature,
            dry_run=args.dry_run,
            backup=not args.no_backup,
            restart=not args.no_restart,
        )
    elif args.action == "status":
        cmd_status(args.feature)


if __name__ == "__main__":
    main()

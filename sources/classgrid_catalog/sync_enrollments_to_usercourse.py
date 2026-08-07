#!/usr/bin/env python3
"""
Load LDAP enrollments into usercourse (and create user stubs by default).

Usage (from backend/):
  .venv/bin/python sources/classgrid_catalog/sync_enrollments_to_usercourse.py
  .venv/bin/python sources/classgrid_catalog/sync_enrollments_to_usercourse.py --replace
  .venv/bin/python sources/classgrid_catalog/sync_enrollments_to_usercourse.py --no-stubs
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


def load_dotenv() -> None:
    env_path = BACKEND_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Overwrite existing usercourse rows (default: only fill empty profiles)",
    )
    parser.add_argument(
        "--no-stubs",
        action="store_true",
        help="Only sync users that already exist (do not create kerberos@iitd.ac.in stubs)",
    )
    parser.add_argument(
        "--include-active",
        action="store_true",
        help="Include the active semester in courses done (default: exclude)",
    )
    args = parser.parse_args()

    load_dotenv()
    from backend.enrollment_sync import sync_all_ldap_enrollments_to_usercourse

    stats = sync_all_ldap_enrollments_to_usercourse(
        create_stubs=not args.no_stubs,
        only_if_empty=not args.replace,
        exclude_active=not args.include_active,
    )
    print("Sync complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

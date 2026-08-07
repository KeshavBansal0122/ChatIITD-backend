#!/usr/bin/env python3
"""
Upsert student hostel values from a CSV export (OAuth identities / LDAP).

Port of Classgrid scripts/db/import_student_hostels.js.

Expected columns: providerAccountId (kerberos), name, hostel

Usage:
  .venv/bin/python sources/classgrid_catalog/import_student_hostels.py
  .venv/bin/python sources/classgrid_catalog/import_student_hostels.py --file=sources/classgrid_catalog/student_hostels.csv
  .venv/bin/python sources/classgrid_catalog/import_student_hostels.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from student_kerberos import is_student_kerberos, normalize_kerberos  # noqa: E402

MIGRATION_SQL = BACKEND_ROOT / "db" / "migrations" / "002_student_enrollments.sql"
DEFAULT_FILE = HERE / "student_hostels.csv"
BATCH = 250


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


def parse_csv_line(line: str) -> dict | None:
    trimmed = line.strip()
    if not trimmed or trimmed.startswith('"providerAccountId"') or trimmed.startswith("providerAccountId"):
        return None
    parts = trimmed.split(",")
    if len(parts) < 3:
        return None
    kerberos = normalize_kerberos(parts[0].strip().strip('"'))
    hostel = parts[-1].strip().strip('"')
    if not kerberos or not hostel or not is_student_kerberos(kerberos):
        return None
    return {"kerberos": kerberos, "hostel": hostel}


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"file not found: {path}")
    rows: list[dict] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        row = parse_csv_line(line)
        if not row or row["kerberos"] in seen:
            continue
        seen.add(row["kerberos"])
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=str(DEFAULT_FILE))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = load_rows(Path(args.file))
    print(f"[import_student_hostels] {len(rows)} rows from {args.file}")
    if args.dry_run:
        print("[import_student_hostels] dry run — first 5:", rows[:5])
        return

    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set")

    import psycopg2

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            # Ensure students table exists
            mig001 = BACKEND_ROOT / "db" / "migrations" / "001_classgrid_catalog.sql"
            if mig001.exists():
                cur.execute(mig001.read_text(encoding="utf-8"))
            cur.execute(MIGRATION_SQL.read_text(encoding="utf-8"))

            for i in range(0, len(rows), BATCH):
                batch = rows[i : i + BATCH]
                kerberos_list = [r["kerberos"] for r in batch]
                hostel_list = [r["hostel"] for r in batch]
                cur.execute(
                    """
                    INSERT INTO students (kerberos, hostel, updated_at)
                    SELECT k, h, now()
                    FROM unnest(%s::text[], %s::text[]) AS t(k, h)
                    ON CONFLICT (kerberos) DO UPDATE SET
                        hostel = EXCLUDED.hostel,
                        updated_at = now()
                    """,
                    (kerberos_list, hostel_list),
                )
                print(
                    f"[import_student_hostels] upserted "
                    f"{min(i + BATCH, len(rows))}/{len(rows)}"
                )
        conn.commit()
        print("[import_student_hostels] done.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

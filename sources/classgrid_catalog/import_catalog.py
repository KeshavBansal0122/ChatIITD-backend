#!/usr/bin/env python3
"""
Import Classgrid-format course catalogs into PostgreSQL.

Creates/updates:
  - semesters
  - catalog_courses  (course_data JSONB includes instructors[])

Usage (from backend/):
  .venv/bin/python sources/classgrid_catalog/import_catalog.py
  .venv/bin/python sources/classgrid_catalog/import_catalog.py --semester=2601
  .venv/bin/python sources/classgrid_catalog/import_catalog.py --dry-run
  .venv/bin/python sources/classgrid_catalog/import_catalog.py --activate=2601

Sources (first match wins per semester code):
  sources/courses_offered/<YYTT>.csv          ← preferred canonical copies
  sources/classgrid_catalog/historical/<YYTT>.csv
  sources/classgrid_catalog/Courses_Offered_<YYTT>.csv
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent.parent
COURSES_OFFERED_DIR = BACKEND_ROOT / "sources" / "courses_offered"
sys.path.insert(0, str(HERE))

from parse_catalog_csv import parse_courses_from_csv  # noqa: E402
from semester_code_meta import semester_meta_from_code  # noqa: E402

MIGRATION_SQL = BACKEND_ROOT / "db" / "migrations" / "001_classgrid_catalog.sql"


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


def compute_catalog_etag(semester_code: str, count: int, stamp: str) -> str:
    raw = f"{semester_code}:{count}:{stamp}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def discover_csv_files(semester_filter: str | None) -> list[tuple[str, Path]]:
    """Prefer sources/courses_offered/<YYTT>.csv, then classgrid_catalog copies."""
    by_code: dict[str, Path] = {}

    hist = HERE / "historical"
    if hist.is_dir():
        for path in sorted(hist.glob("*.csv")):
            code = path.stem
            if code.isdigit() and len(code) == 4:
                by_code[code] = path

    for path in sorted(HERE.glob("Courses_Offered_*.csv")):
        code = path.stem.replace("Courses_Offered_", "")
        if code.isdigit() and len(code) == 4:
            by_code[code] = path

    if COURSES_OFFERED_DIR.is_dir():
        for path in sorted(COURSES_OFFERED_DIR.glob("*.csv")):
            code = path.stem
            if code.isdigit() and len(code) == 4:
                by_code[code] = path

    files = sorted(by_code.items(), key=lambda x: x[0])
    if semester_filter:
        files = [(c, p) for c, p in files if c == semester_filter]
    return files

def upsert_semester(cur, semester_code: str, meta: dict, *, force_dates: bool = True) -> None:
    cur.execute(
        """
        INSERT INTO semesters (code, label, classes_start, last_teaching_day, is_active, academic_calendar)
        VALUES (%s, %s, %s, %s, false, '{}'::jsonb)
        ON CONFLICT (code) DO UPDATE SET
            label = COALESCE(NULLIF(semesters.label, ''), EXCLUDED.label),
            classes_start = CASE
                WHEN semesters.is_active AND NOT %s THEN semesters.classes_start
                ELSE EXCLUDED.classes_start
            END,
            last_teaching_day = CASE
                WHEN semesters.is_active AND NOT %s THEN semesters.last_teaching_day
                ELSE EXCLUDED.last_teaching_day
            END,
            updated_at = now()
        """,
        (
            semester_code,
            meta["label"],
            meta["classes_start"],
            meta["last_teaching_day"],
            force_dates,
            force_dates,
        ),
    )


def import_catalog_for_semester(cur, semester_code: str, courses: list[dict]) -> int:
    # Preserve lecture halls if we ever set them later
    cur.execute(
        "SELECT course_code, course_data FROM catalog_courses WHERE semester_code = %s",
        (semester_code,),
    )
    hall_by_code = {
        row[0]: (row[1] or {}).get("lectureHall")
        for row in cur.fetchall()
        if isinstance(row[1], dict)
    }

    cur.execute("DELETE FROM catalog_courses WHERE semester_code = %s", (semester_code,))

    by_code: dict[str, dict] = {}
    for course in courses:
        by_code[str(course["courseCode"]).upper()] = course
    unique = list(by_code.values())

    for course in unique:
        cc = str(course["courseCode"]).upper()
        course["courseCode"] = cc
        preserved = hall_by_code.get(cc)
        if preserved and not course.get("lectureHall"):
            course["lectureHall"] = preserved
        cur.execute(
            """
            INSERT INTO catalog_courses (semester_code, course_code, course_data)
            VALUES (%s, %s, %s::jsonb)
            """,
            (semester_code, cc, json.dumps(course)),
        )

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    etag = compute_catalog_etag(semester_code, len(unique), now)
    cur.execute(
        """
        UPDATE semesters
        SET catalog_etag = %s, catalog_updated_at = now(), updated_at = now()
        WHERE code = %s
        """,
        (etag, semester_code),
    )
    return len(unique)


def activate_semester(cur, semester_code: str) -> None:
    cur.execute("UPDATE semesters SET is_active = false WHERE is_active = true")
    cur.execute(
        "UPDATE semesters SET is_active = true, updated_at = now() WHERE code = %s",
        (semester_code,),
    )
    if cur.rowcount != 1:
        raise SystemExit(f"Cannot activate unknown semester {semester_code}")


def apply_migration(cur) -> None:
    sql = MIGRATION_SQL.read_text(encoding="utf-8")
    cur.execute(sql)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Classgrid catalog CSVs")
    parser.add_argument("--semester", help="Import only this YYTT semester code")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no DB writes")
    parser.add_argument("--activate", help="Mark this semester active after import")
    parser.add_argument(
        "--skip-migration",
        action="store_true",
        help="Do not apply 001_classgrid_catalog.sql",
    )
    args = parser.parse_args()

    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url and not args.dry_run:
        raise SystemExit("DATABASE_URL not set")

    files = discover_csv_files(args.semester)
    if not files:
        raise SystemExit("No catalog CSV files found to import.")

    print(f"Found {len(files)} catalog file(s)")
    parsed: list[tuple[str, Path, list]] = []
    for code, path in files:
        courses = parse_courses_from_csv(path, code)
        with_email = sum(1 for c in courses if c.get("instructorEmail"))
        multi = sum(1 for c in courses if len(c.get("instructors") or []) > 1)
        print(
            f"  {code}: {len(courses)} courses "
            f"({with_email} with email, {multi} multi-instructor) ← {path.name}"
        )
        parsed.append((code, path, courses))

    if args.dry_run:
        print("Dry run complete — no database changes.")
        return

    try:
        import psycopg2
        from psycopg2.extras import Json  # noqa: F401
    except ImportError as e:
        raise SystemExit(f"psycopg2 required: {e}") from e

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            if not args.skip_migration:
                print(f"Applying migration {MIGRATION_SQL.name} ...")
                apply_migration(cur)

            total = 0
            for code, _path, courses in parsed:
                meta = semester_meta_from_code(code)
                upsert_semester(cur, code, meta)
                count = import_catalog_for_semester(cur, code, courses)
                total += count
                print(f"Imported {count} courses for {code} ({meta['label']})")

            if args.activate:
                activate_semester(cur, args.activate)
                print(f"Activated semester {args.activate}")
            else:
                # If nothing active yet, activate the newest imported semester
                cur.execute("SELECT 1 FROM semesters WHERE is_active = true LIMIT 1")
                if cur.fetchone() is None and parsed:
                    newest = max(code for code, _, _ in parsed)
                    activate_semester(cur, newest)
                    print(f"Activated newest semester {newest}")

        conn.commit()
        print(f"Done. {total} total catalog rows across {len(parsed)} semester(s).")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

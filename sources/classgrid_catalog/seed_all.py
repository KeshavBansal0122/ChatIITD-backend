#!/usr/bin/env python3
"""
One-shot seed for ChatIITD Postgres: app tables, catalog (+ instructors),
LDAP enrollments/rosters (from local JSON), hostels, and usercourse stubs.

Used by Docker build (preloaded postgres image) and local bring-up.

Usage (from backend/, DATABASE_URL set):
  python sources/classgrid_catalog/seed_all.py
  python sources/classgrid_catalog/seed_all.py --activate=2601
  python sources/classgrid_catalog/seed_all.py --skip-enrollments
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent.parent
MIGRATIONS = [
    BACKEND_ROOT / "db" / "migrations" / "001_classgrid_catalog.sql",
    BACKEND_ROOT / "db" / "migrations" / "002_student_enrollments.sql",
    BACKEND_ROOT / "db" / "migrations" / "003_llm_usage_and_credentials.sql",
]
DEFAULT_EXPORT_ROOT = HERE / "ldap_exports"
PY = sys.executable


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


def run(cmd: list[str], *, check: bool = True) -> int:
    print("+", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=str(BACKEND_ROOT))
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result.returncode


def apply_migrations(database_url: str) -> None:
    import psycopg2

    conn = psycopg2.connect(database_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for path in MIGRATIONS:
                if not path.exists():
                    print(f"[seed] skip missing migration {path.name}")
                    continue
                print(f"[seed] applying {path.name}")
                cur.execute(path.read_text(encoding="utf-8"))
    finally:
        conn.close()


def discover_local_enrollment_semesters(export_root: Path) -> list[str]:
    if not export_root.is_dir():
        return []
    codes: list[str] = []
    for child in sorted(export_root.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "studentCourses.json").exists():
            continue
        if child.name.isdigit() and len(child.name) == 4:
            codes.append(child.name)
    return codes


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed ChatIITD database")
    parser.add_argument("--activate", default="2601", help="Active semester YYTT")
    parser.add_argument(
        "--skip-enrollments",
        action="store_true",
        help="Skip LDAP JSON import + usercourse sync",
    )
    parser.add_argument(
        "--skip-usercourse",
        action="store_true",
        help="Import enrollments but do not fill usercourse stubs",
    )
    parser.add_argument(
        "--skip-legacy-offerings",
        action="store_true",
        help="Skip sources/courses_offered.csv → courseoffering",
    )
    parser.add_argument(
        "--require-enrollments",
        action="store_true",
        help="Fail if ldap_exports/ is missing (Docker full seed)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_EXPORT_ROOT),
        help="LDAP JSON export root",
    )
    args = parser.parse_args()

    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    os.environ["DATABASE_URL"] = database_url
    sys.path.insert(0, str(BACKEND_ROOT))

    print("[seed] init_db (app tables + courses.sqlite descriptions)")
    from backend.models import init_db

    init_db()
    apply_migrations(database_url)

    print("[seed] catalog + instructors (Courses_Offered CSVs)")
    run(
        [
            PY,
            "sources/classgrid_catalog/import_catalog.py",
            f"--activate={args.activate}",
            "--skip-migration",
        ]
    )

    export_root = Path(args.out_dir)
    semesters = discover_local_enrollment_semesters(export_root)

    if args.skip_enrollments:
        print("[seed] skipping enrollments (--skip-enrollments)")
    elif not semesters:
        msg = f"[seed] no LDAP JSON under {export_root}"
        if args.require_enrollments:
            raise SystemExit(msg + " (required for this build)")
        print(msg + " — continuing without student data")
    else:
        print(f"[seed] importing enrollments for {semesters}")
        for code in semesters:
            run(
                [
                    PY,
                    "sources/classgrid_catalog/import_student_data.py",
                    f"--semester={code}",
                    "--from-json",
                    f"--out-dir={export_root}",
                ]
            )

        hostels = HERE / "student_hostels.csv"
        if hostels.exists():
            print("[seed] student hostels")
            run([PY, "sources/classgrid_catalog/import_student_hostels.py"])
        else:
            print("[seed] no student_hostels.csv — skip")

        if not args.skip_usercourse:
            print("[seed] sync LDAP → usercourse (+ user stubs)")
            run(
                [
                    PY,
                    "sources/classgrid_catalog/sync_enrollments_to_usercourse.py",
                    "--replace",
                ]
            )

    offerings = BACKEND_ROOT / "sources" / "courses_offered.csv"
    if not args.skip_legacy_offerings and offerings.exists():
        print("[seed] legacy courseoffering CSV")
        run([PY, "sources/import_offerings.py"], check=False)
    else:
        print("[seed] skip legacy offerings")

    import psycopg2

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM catalog_courses")
            catalog = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM student_enrollments")
            enroll = cur.fetchone()[0]
            cur.execute('SELECT count(*) FROM "user"')
            users = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM usercourse")
            courses_done = cur.fetchone()[0]
            cur.execute("SELECT code FROM semesters WHERE is_active = true LIMIT 1")
            active = cur.fetchone()
        print(
            "[seed] done — "
            f"catalog_courses={catalog}, enrollments={enroll}, "
            f"users={users}, usercourse={courses_done}, "
            f"active={active[0] if active else None}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Fetch student enrollments + course rosters from IITD LDAP and import to Postgres.

Port of Classgrid scripts/db/import_student_data.js.

LDAP (ldapweb.iitd.ac.in) is only reachable on IITD intranet / VPN.
The LDAP TLS cert is often incomplete — this script disables verification
(same as Classgrid's NODE_TLS_REJECT_UNAUTHORIZED=0).

Usage (from backend/):
  # VPN: fetch JSON only
  .venv/bin/python sources/classgrid_catalog/import_student_data.py --semester=2601 --fetch-only

  # Import previously fetched JSON
  .venv/bin/python sources/classgrid_catalog/import_student_data.py --semester=2601 --from-json

  # VPN: fetch + import
  .venv/bin/python sources/classgrid_catalog/import_student_data.py --semester=2601

  # All catalog semesters that exist on LDAP
  .venv/bin/python sources/classgrid_catalog/import_student_data.py --all-available

Requires a `semesters` row for the target semester (run import_catalog.py first).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from student_kerberos import (  # noqa: E402
    filter_student_enrollment_data,
    is_student_kerberos,
    normalize_kerberos,
)

BASE_URL = "https://ldapweb.iitd.ac.in/LDAP/courses"
MIGRATION_SQL = BACKEND_ROOT / "db" / "migrations" / "002_student_enrollments.sql"
DEFAULT_EXPORT_ROOT = HERE / "ldap_exports"
LINK_RE = re.compile(r'href="([^"]+)"', re.I)
ROW_RE = re.compile(
    r"<TR><TD[^>]*>([a-z0-9]+)</TD>\s*<TD>([^<]+)</TD>",
    re.I,
)
COURSE_CODE_RE = re.compile(r"-([A-Z0-9]+)\.")
BATCH_SIZE = 40


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


async def list_ldap_semester_prefixes(client: httpx.AsyncClient) -> dict[str, int]:
    res = await client.get(f"{BASE_URL}/gpaliases.html")
    res.raise_for_status()
    counts: dict[str, int] = {}
    for link in LINK_RE.findall(res.text):
        m = re.match(r"^(\d{4})-", link)
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


async def fetch_student_data_from_ldap(
    client: httpx.AsyncClient, prefix: str
) -> tuple[dict, dict]:
    print(f"Fetching course pages from {BASE_URL} (prefix {prefix})…")
    print("Requires IITD intranet or VPN.")

    res = await client.get(f"{BASE_URL}/gpaliases.html")
    res.raise_for_status()
    links = [
        link
        for link in LINK_RE.findall(res.text)
        if link.startswith(prefix) and (link.endswith(".shtml") or link.endswith(".html"))
    ]
    print(f"Found {len(links)} course pages.")
    if not links:
        print(
            f'No links matched prefix "{prefix}". '
            "Check --semester / --prefix, or confirm you are on IITD VPN."
        )

    student_courses: dict[str, list[str]] = {}
    course_students: dict[str, list[dict]] = {}

    async def process_link(link: str) -> None:
        m = COURSE_CODE_RE.search(link)
        if not m:
            return
        course_code = m.group(1)
        try:
            course_res = await client.get(f"{BASE_URL}/{link}")
            if course_res.status_code != 200:
                return
            for row in ROW_RE.finditer(course_res.text):
                kid = normalize_kerberos(row.group(1))
                name = row.group(2).strip()
                if not is_student_kerberos(kid):
                    continue
                student_courses.setdefault(kid, [])
                if course_code not in student_courses[kid]:
                    student_courses[kid].append(course_code)
                roster = course_students.setdefault(course_code, [])
                if not any(s["id"] == kid for s in roster):
                    roster.append({"id": kid, "name": name})
        except Exception as err:  # noqa: BLE001
            print(f"Error processing {link}: {err}")

    for i in range(0, len(links), BATCH_SIZE):
        batch = links[i : i + BATCH_SIZE]
        print(f"Processing batch {i + 1}-{min(i + BATCH_SIZE, len(links))} / {len(links)}…")
        await asyncio.gather(*(process_link(link) for link in batch))

    return student_courses, course_students


def write_json_export(
    out_dir: Path,
    semester_code: str,
    prefix: str,
    student_courses: dict,
    course_students: dict,
    skipped: int,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "studentCourses.json").write_text(
        json.dumps(student_courses, indent=2), encoding="utf-8"
    )
    (out_dir / "courseStudents.json").write_text(
        json.dumps(course_students, indent=2), encoding="utf-8"
    )
    meta = {
        "semesterCode": semester_code,
        "semesterPrefix": prefix,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "studentCount": len(student_courses),
        "courseCount": len(course_students),
        "skippedNonStudentKerberos": skipped,
        "studentKerberosFormat": "aa1234567|abc123456",
        "source": BASE_URL,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Wrote {out_dir / 'studentCourses.json'}")
    print(f"Wrote {out_dir / 'courseStudents.json'}")
    print(f"Wrote {out_dir / 'meta.json'}")


def read_json_export(out_dir: Path) -> tuple[dict, dict]:
    student_path = out_dir / "studentCourses.json"
    roster_path = out_dir / "courseStudents.json"
    if not student_path.exists() or not roster_path.exists():
        raise SystemExit(
            f"Missing JSON in {out_dir}. Run with --fetch-only on VPN first."
        )
    return (
        json.loads(student_path.read_text(encoding="utf-8")),
        json.loads(roster_path.read_text(encoding="utf-8")),
    )


def apply_migration(cur) -> None:
    mig001 = BACKEND_ROOT / "db" / "migrations" / "001_classgrid_catalog.sql"
    if mig001.exists():
        cur.execute(mig001.read_text(encoding="utf-8"))
    cur.execute(MIGRATION_SQL.read_text(encoding="utf-8"))


def import_to_postgres(
    semester_code: str,
    student_courses: dict,
    course_students: dict,
    skipped: int,
    *,
    dry_run: bool,
) -> None:
    if dry_run:
        print(
            f"[dry-run] Would import {len(student_courses)} students, "
            f"{len(course_students)} course rosters for {semester_code}"
            + (f" ({skipped} non-student kerberos skipped)" if skipped else "")
        )
        return

    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set")

    import psycopg2
    from psycopg2.extras import execute_batch

    conn = psycopg2.connect(database_url)
    enroll_rows: list[tuple] = []
    roster_rows: list[tuple] = []
    try:
        with conn.cursor() as cur:
            apply_migration(cur)
            cur.execute("SELECT code FROM semesters WHERE code = %s", (semester_code,))
            if cur.fetchone() is None:
                raise SystemExit(
                    f"No semesters row for {semester_code}. "
                    "Run import_catalog.py / sync_from_classgrid_api.py first."
                )

            cur.execute(
                "DELETE FROM student_enrollments WHERE semester_code = %s",
                (semester_code,),
            )
            cur.execute(
                "DELETE FROM course_rosters WHERE semester_code = %s",
                (semester_code,),
            )

            enroll_rows = [
                (semester_code, kerberos, str(cc).upper())
                for kerberos, courses in student_courses.items()
                for cc in courses
            ]
            execute_batch(
                cur,
                """
                INSERT INTO student_enrollments (semester_code, kerberos, course_code)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                """,
                enroll_rows,
                page_size=500,
            )

            roster_rows = [
                (
                    semester_code,
                    str(course_code).upper(),
                    row["id"],
                    row.get("name") or "",
                )
                for course_code, roster in course_students.items()
                for row in roster
            ]
            execute_batch(
                cur,
                """
                INSERT INTO course_rosters
                    (semester_code, course_code, student_kerberos, student_name)
                VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                roster_rows,
                page_size=500,
            )

        conn.commit()
        print(
            f"Imported {len(student_courses)} students, "
            f"{len(course_students)} course rosters for {semester_code} "
            f"({len(enroll_rows)} enrollment rows, {len(roster_rows)} roster rows)"
            + (f"; skipped {skipped} non-student" if skipped else "")
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def process_semester(
    semester_code: str,
    *,
    prefix: str,
    fetch_only: bool,
    from_json: bool,
    dry_run: bool,
    out_root: Path,
    client: httpx.AsyncClient | None,
) -> None:
    out_dir = out_root / semester_code
    skipped = 0

    if from_json:
        print(f"Loading JSON from {out_dir}…")
        student_courses, course_students = read_json_export(out_dir)
        student_courses, course_students, skipped = filter_student_enrollment_data(
            student_courses, course_students
        )
    else:
        assert client is not None
        student_courses, course_students = await fetch_student_data_from_ldap(
            client, prefix
        )
        student_courses, course_students, skipped = filter_student_enrollment_data(
            student_courses, course_students
        )
        if skipped:
            print(
                f"[import_student_data] skipped {skipped} non-student kerberos "
                "(expected format: aa1234567 or abc123456)"
            )
        write_json_export(
            out_dir, semester_code, prefix, student_courses, course_students, skipped
        )

    if fetch_only:
        print(
            f"Fetch-only complete ({len(student_courses)} students). "
            "Import later with --from-json."
        )
        return

    import_to_postgres(
        semester_code, student_courses, course_students, skipped, dry_run=dry_run
    )


async def async_main(args: argparse.Namespace) -> None:
    out_root = Path(args.out_dir) if args.out_dir else DEFAULT_EXPORT_ROOT
    semesters: list[str] = []

    if args.all_available:
        load_dotenv()
        import psycopg2

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise SystemExit("DATABASE_URL required for --all-available")
        async with httpx.AsyncClient(
            timeout=60.0, verify=False, follow_redirects=True
        ) as client:
            ldap_counts = await list_ldap_semester_prefixes(client)
        conn = psycopg2.connect(database_url)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT code FROM semesters ORDER BY code")
                db_codes = [r[0] for r in cur.fetchall()]
        finally:
            conn.close()
        semesters = [c for c in db_codes if c in ldap_counts]
        print(
            f"--all-available: will process {semesters} "
            f"(LDAP also has {[c for c in sorted(ldap_counts) if c not in db_codes]})"
        )
    elif args.semester:
        semesters = [args.semester]
    else:
        raise SystemExit("Provide --semester=CODE or --all-available")

    if args.from_json:
        for code in semesters:
            prefix = args.prefix or f"{code}-"
            await process_semester(
                code,
                prefix=prefix,
                fetch_only=args.fetch_only,
                from_json=True,
                dry_run=args.dry_run,
                out_root=out_root,
                client=None,
            )
        return

    async with httpx.AsyncClient(
        timeout=60.0, verify=False, follow_redirects=True
    ) as client:
        for code in semesters:
            prefix = args.prefix or f"{code}-"
            await process_semester(
                code,
                prefix=prefix,
                fetch_only=args.fetch_only,
                from_json=False,
                dry_run=args.dry_run,
                out_root=out_root,
                client=client,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import LDAP student enrollments")
    parser.add_argument("--semester", help="IITD semester code (e.g. 2601)")
    parser.add_argument("--all-available", action="store_true")
    parser.add_argument("--prefix", help="LDAP page prefix (default: SEMESTER-)")
    parser.add_argument("--out-dir", help="JSON export root directory")
    parser.add_argument("--from-json", action="store_true")
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()

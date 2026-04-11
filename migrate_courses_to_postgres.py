"""
Migration script: courses.sqlite → PostgreSQL

Reads all data from courses.sqlite (kept as a backup) and inserts it into
the PostgreSQL database managed by SQLModel.

Also merges the richer `instructor` field from the JSONL offerings file.

Usage:
    DATABASE_URL=postgresql://... python migrate_courses_to_postgres.py

Run this once after starting the PostgreSQL container.
Safe to re-run: uses INSERT OR IGNORE semantics (skips existing rows).
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

# Allow importing the backend package
sys.path.insert(0, str(Path(__file__).parent))

from backend.models import Course, CourseOffering, CourseOverlap, get_engine, get_session
from sqlmodel import SQLModel, select

BACKEND_DIR = Path(__file__).parent
COURSES_SQLITE = BACKEND_DIR / "courses.sqlite"
JSONL_DIR = BACKEND_DIR / "sources" / "jsonl"
OFFERINGS_JSONL = JSONL_DIR / "courses_offered.jsonl"


def read_jsonl(path: Path) -> list[dict]:
    result = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                result.append(json.loads(line))
    return result


def migrate():
    print("Connecting to PostgreSQL and creating tables...")
    engine = get_engine()
    SQLModel.metadata.create_all(engine)

    # Build instructor lookup from JSONL: (year, semester, code) → instructor
    instructor_map: dict[tuple, str] = {}
    if OFFERINGS_JSONL.exists():
        for row in read_jsonl(OFFERINGS_JSONL):
            key = (str(row.get("year", "")), int(row.get("semester", 0)), row.get("course_code", "").upper())
            instructor_map[key] = row.get("instructor", "")
        print(f"Loaded {len(instructor_map)} instructor records from JSONL")

    conn = sqlite3.connect(f"file:{COURSES_SQLITE}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    with get_session() as sess:
        # ── Courses ──────────────────────────────────────────────────────────
        cur.execute("SELECT * FROM courses")
        courses = cur.fetchall()
        inserted_courses = 0
        skipped_courses = 0
        for row in courses:
            existing = sess.get(Course, row["code"])
            if existing:
                skipped_courses += 1
                continue
            c = Course(
                code=row["code"],
                name=row["name"],
                description=row["description"],
                hours_lecture=row["hours_lecture"],
                hours_tutorial=row["hours_tutorial"],
                hours_practical=row["hours_practical"],
                credits=row["credits"],
                prereq=row["prereq"],
                overlap=row["overlap"],
            )
            sess.add(c)
            inserted_courses += 1
        sess.commit()
        print(f"Courses: inserted={inserted_courses}, skipped={skipped_courses}")

        # ── Offerings ────────────────────────────────────────────────────────
        cur.execute("SELECT * FROM offerings")
        offerings = cur.fetchall()
        inserted_offerings = 0
        for row in offerings:
            year = row["year"] or ""
            semester = row["semester"] or 0
            code = (row["code"] or "").upper()
            instructor = instructor_map.get((year, semester, code), row["coordinator"] or "")

            o = CourseOffering(
                code=code,
                year=year,
                semester=semester,
                coordinator=row["coordinator"],
                instructor=instructor,
                slot=row["slot"],
            )
            sess.add(o)
            inserted_offerings += 1
        sess.commit()
        print(f"Offerings: inserted={inserted_offerings}")

        # ── Overlaps ─────────────────────────────────────────────────────────
        cur.execute("SELECT * FROM overlaps")
        overlaps = cur.fetchall()
        inserted_overlaps = 0
        for row in overlaps:
            o = CourseOverlap(
                code_1=row["code_1"],
                code_2=row["code_2"],
            )
            sess.add(o)
            inserted_overlaps += 1
        sess.commit()
        print(f"Overlaps: inserted={inserted_overlaps}")

    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    migrate()

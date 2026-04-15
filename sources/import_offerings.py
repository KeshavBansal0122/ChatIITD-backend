"""
Import course offerings from courses_offered.csv into the PostgreSQL courseoffering table.

Usage (from backend/sources/):
    python import_offerings.py

Reads DATABASE_URL from backend/.env. Skips rows that already exist
(matched on code + year + semester + instructor).
"""

import csv
import os
import sys
from pathlib import Path

# Load .env from backend/
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"'))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL not set")

try:
    import psycopg2
except ImportError:
    sys.exit("psycopg2 not installed — run: pip install psycopg2-binary")

CSV_PATH = Path(__file__).resolve().parent / "courses_offered.csv"


def parse_semester(value: str) -> int | None:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Fetch existing (code, year, semester, instructor) to detect conflicts
    cur.execute("SELECT code, year, semester, instructor FROM courseoffering")
    existing = {row for row in cur.fetchall()}

    inserted = skipped = 0

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row["Course Code"].strip()
            year = row["Year"].strip()
            semester = parse_semester(row["Semester"].strip())
            slot = (row.get("Slot") or "").strip() or None
            instructor = (row.get("Instructor") or "").strip() or None

            key = (code, year, semester, instructor)
            if key in existing:
                skipped += 1
                continue

            cur.execute(
                """
                INSERT INTO courseoffering (code, year, semester, slot, instructor)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (code, year, semester, slot, instructor),
            )
            existing.add(key)
            inserted += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"Done — inserted: {inserted}, skipped (conflicts): {skipped}")


if __name__ == "__main__":
    main()

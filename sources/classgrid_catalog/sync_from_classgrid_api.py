#!/usr/bin/env python3
"""
Refresh the active-semester catalog from Classgrid's public API.

Use this when you don't have a fresh Courses_Offered CSV. Classgrid has no CORS
headers — call only from the backend (never the browser).

Usage:
  .venv/bin/python sources/classgrid_catalog/sync_from_classgrid_api.py
  .venv/bin/python sources/classgrid_catalog/sync_from_classgrid_api.py --base-url=https://classgrid.devclub.in
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from import_catalog import (  # noqa: E402
    activate_semester,
    apply_migration,
    import_catalog_for_semester,
    load_dotenv,
    upsert_semester,
)
from semester_code_meta import semester_meta_from_code  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.environ.get("CLASSGRID_BASE_URL", "https://classgrid.devclub.in"),
    )
    parser.add_argument("--activate", action="store_true", help="Mark fetched semester active")
    args = parser.parse_args()

    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL not set")

    base = args.base_url.rstrip("/")
    with httpx.Client(timeout=60.0) as client:
        health = client.get(f"{base}/api/health")
        health.raise_for_status()
        print("health:", health.json())

        catalog = client.get(f"{base}/api/catalog")
        catalog.raise_for_status()
        payload = catalog.json()
        semester_code = payload.get("semesterCode")
        courses = payload.get("courses") or []
        if not semester_code:
            raise SystemExit("No semesterCode in /api/catalog response")
        print(f"Fetched {len(courses)} courses for {semester_code}")

    # Ensure Classgrid-shaped fields exist
    for course in courses:
        course.setdefault("semesterCode", semester_code)
        course.setdefault("lectureHall", None)
        if "instructors" not in course:
            course["instructors"] = []

    import psycopg2

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            apply_migration(cur)
            meta = semester_meta_from_code(semester_code)
            upsert_semester(cur, semester_code, meta)
            count = import_catalog_for_semester(cur, semester_code, courses)
            if args.activate:
                activate_semester(cur, semester_code)
            print(f"Imported {count} courses for {semester_code}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

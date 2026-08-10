#!/usr/bin/env python3
"""
Import scraped courses.iitd.ac.in JSON into Postgres `course` table.

Usage (DATABASE_URL set, from backend/):
  python sources/courses_iitd/import_courses_iitd.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent.parent
COURSE_DIR = HERE / "courses"


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
    load_dotenv()
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is required")
    sys.path.insert(0, str(BACKEND_ROOT))

    from backend.models import Course, get_session

    # Prefer code-named files (avoid double-counting slug duplicates)
    by_code: dict[str, dict] = {}
    for path in sorted(COURSE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        code = (data.get("code") or "").upper().strip()
        if not code:
            continue
        # Prefer richer description if duplicate
        prev = by_code.get(code)
        if prev and len(prev.get("description") or "") >= len(data.get("description") or ""):
            continue
        by_code[code] = data

    inserted = 0
    updated = 0
    with get_session() as sess:
        for code, data in by_code.items():
            hours = data.get("hours") or {}
            existing = sess.get(Course, code)
            if existing:
                # Fill missing description / metadata; don't wipe legacy-only fields blindly
                if data.get("description"):
                    existing.description = data["description"]
                if data.get("name"):
                    existing.name = data["name"]
                if data.get("credits") is not None:
                    existing.credits = data["credits"]
                existing.hours_lecture = hours.get("lecture", existing.hours_lecture)
                existing.hours_tutorial = hours.get("tutorial", existing.hours_tutorial)
                existing.hours_practical = hours.get("practical", existing.hours_practical)
                if data.get("prereq"):
                    existing.prereq = data["prereq"]
                if data.get("overlap"):
                    existing.overlap = data["overlap"]
                if data.get("learning_outcomes"):
                    existing.learning_outcomes = data["learning_outcomes"]
                existing.generation = data.get("generation") or existing.generation or "2025"
                existing.academic_unit = data.get("department") or existing.academic_unit
                existing.source = "courses_iitd"
                existing.source_url = data.get("source_url")
                updated += 1
            else:
                sess.add(
                    Course(
                        code=code,
                        name=data.get("name"),
                        description=data.get("description"),
                        credits=data.get("credits"),
                        hours_lecture=hours.get("lecture"),
                        hours_tutorial=hours.get("tutorial"),
                        hours_practical=hours.get("practical"),
                        prereq=data.get("prereq"),
                        overlap=data.get("overlap"),
                        learning_outcomes=data.get("learning_outcomes"),
                        generation=data.get("generation") or "2025",
                        academic_unit=data.get("department"),
                        source="courses_iitd",
                        source_url=data.get("source_url"),
                    )
                )
                inserted += 1
        sess.commit()

    print(f"[courses_iitd] inserted={inserted} updated={updated} total_files={len(by_code)}")


if __name__ == "__main__":
    main()

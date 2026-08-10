#!/usr/bin/env python3
"""
Import curriculum into Postgres:
- legacy programmes from sources/programme_structures/*.json
- 2025 programmes/courses from sources/curriculum_2025/

Usage (DATABASE_URL set, from backend/):
  python sources/curriculum_2025/import_curriculum.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent.parent
LEGACY_PROG_DIR = BACKEND_ROOT / "sources" / "programme_structures"
PROG_DIR = HERE / "programmes"
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


def import_legacy_programmes(sess) -> int:
    from backend.models import (
        Programme,
        ProgrammeCourse,
        ProgrammeCreditReq,
        ProgrammeSemester,
    )

    count = 0
    for path in sorted(LEGACY_PROG_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        code = data["code"].upper()
        existing = sess.get(Programme, (code, "legacy"))
        if existing:
            continue
        sess.add(
            Programme(
                code=code,
                generation="legacy",
                name=data.get("name"),
                degree_type="dual" if data.get("dual") else "btech",
                dual=bool(data.get("dual")),
                source_url=None,
                raw=data,
            )
        )
        for cat, credits in (data.get("credits") or {}).items():
            sess.add(
                ProgrammeCreditReq(
                    programme_code=code,
                    generation="legacy",
                    category=cat,
                    label=cat,
                    credits_or_units=float(credits) if credits is not None else None,
                    kind="graded",
                )
            )
        for cat, codes in (data.get("courses") or {}).items():
            for cc in codes:
                sess.add(
                    ProgrammeCourse(
                        programme_code=code,
                        generation="legacy",
                        course_code=str(cc).upper(),
                        category=cat,
                        is_core=(cat in ("DC", "PL", "BS", "EAS")),
                    )
                )
        for i, entries in enumerate(data.get("recommended") or [], start=1):
            sess.add(
                ProgrammeSemester(
                    programme_code=code,
                    generation="legacy",
                    semester=i,
                    entries=[{"course_code": c} if isinstance(c, str) else c for c in entries],
                )
            )
        count += 1
    sess.commit()
    return count


def import_2025_courses(sess) -> int:
    from backend.models import Course

    n = 0
    for path in sorted(COURSE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        code = data["code"].upper()
        existing = sess.get(Course, code)
        hours = data.get("hours") or {}
        if existing:
            # Refresh 2025 metadata if missing
            if existing.generation != "2025":
                # Prefer not to overwrite legacy codes (shouldn't collide)
                continue
            existing.name = data.get("name") or existing.name
            existing.description = data.get("description") or existing.description
            existing.credits = data.get("credits") if data.get("credits") is not None else existing.credits
            existing.hours_lecture = hours.get("lecture")
            existing.hours_tutorial = hours.get("tutorial")
            existing.hours_practical = hours.get("practical")
            existing.learning_outcomes = data.get("learning_outcomes")
            existing.academic_unit = data.get("academic_unit")
            existing.source = "curriculum_web"
            existing.source_url = data.get("source_url")
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
                    generation="2025",
                    academic_unit=data.get("academic_unit"),
                    learning_outcomes=data.get("learning_outcomes"),
                    source="curriculum_web",
                    source_url=data.get("source_url"),
                )
            )
            n += 1
    sess.commit()
    return n


def import_2025_programmes(sess) -> int:
    from backend.models import (
        Programme,
        ProgrammeCourse,
        ProgrammeCreditReq,
        ProgrammeOutcome,
        ProgrammeSemester,
    )

    count = 0
    for path in sorted(PROG_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        code = data["code"].upper()
        if sess.get(Programme, (code, "2025")):
            continue
        sess.add(
            Programme(
                code=code,
                generation="2025",
                name=data.get("name"),
                degree_type=data.get("degree_type"),
                dual=bool(data.get("dual")),
                source_url=data.get("source_url"),
                raw=data,
            )
        )
        for req in data.get("credit_requirements") or []:
            sess.add(
                ProgrammeCreditReq(
                    programme_code=code,
                    generation="2025",
                    category=req["category"],
                    label=req.get("label"),
                    credits_or_units=req.get("credits_or_units"),
                    kind=req.get("kind") or "graded",
                )
            )
        for cat, courses in (data.get("courses_by_category") or {}).items():
            for c in courses:
                cc = (c.get("course_code") or "").upper()
                if not cc:
                    continue
                sess.add(
                    ProgrammeCourse(
                        programme_code=code,
                        generation="2025",
                        course_code=cc,
                        category=cat,
                        is_core=True,
                    )
                )
        for sem_str, entries in (data.get("semesters") or {}).items():
            try:
                sem = int(sem_str)
            except ValueError:
                continue
            sess.add(
                ProgrammeSemester(
                    programme_code=code,
                    generation="2025",
                    semester=sem,
                    entries=entries,
                )
            )
        for out in data.get("outcomes") or []:
            sess.add(
                ProgrammeOutcome(
                    programme_code=code,
                    generation="2025",
                    outcome_id=out.get("outcome_id") or "PLO",
                    text=out.get("text") or "",
                )
            )
        count += 1
    sess.commit()
    return count


def main() -> None:
    load_dotenv()
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is required")
    sys.path.insert(0, str(BACKEND_ROOT))

    from backend.models import get_session

    with get_session() as sess:
        legacy_n = import_legacy_programmes(sess)
        print(f"[curriculum] legacy programmes inserted: {legacy_n}")
        if COURSE_DIR.is_dir() and any(COURSE_DIR.glob("*.json")):
            c_n = import_2025_courses(sess)
            print(f"[curriculum] 2025 courses inserted: {c_n}")
        else:
            print("[curriculum] no curriculum_2025/courses — skip 2025 courses")
        if PROG_DIR.is_dir() and any(PROG_DIR.glob("*.json")):
            p_n = import_2025_programmes(sess)
            print(f"[curriculum] 2025 programmes inserted: {p_n}")
        else:
            print("[curriculum] no curriculum_2025/programmes — skip 2025 programmes")


if __name__ == "__main__":
    main()

"""
Parse IITD Courses_Offered CSV into Classgrid course_data objects.

Port of ../classgrid/scripts/db/parse_catalog_csv.js
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from parse_instructors import attach_instructors, resolve_instructor_emails

DAYS_MAP = {"M": "1", "T": "2", "W": "3", "Th": "4", "F": "5", "S": "6", "Su": "7"}
UNITS_RE = re.compile(r"^\d+(\.\d+)?-\d+(\.\d+)?-\d+(\.\d+)?$")
TIMING_RE = re.compile(r"([A-Za-z]+)\s+(\d{1,2}:\d{2})-(\d{1,2}:\d{2})")


def parse_credit_structure(units_str: str) -> float:
    try:
        parts = [float(p) for p in units_str.split("-")]
        if len(parts) == 3:
            return parts[0] + parts[1] + 0.5 * parts[2]
    except (TypeError, ValueError):
        pass
    return 0.0


def clean_course_code(name_str: str) -> str:
    if not name_str:
        return ""
    trimmed = name_str.strip()
    idx = trimmed.rfind("-")
    if idx != -1:
        return trimmed[idx + 1 :].strip()
    return trimmed


def extract_course_name(name_str: str) -> str:
    if not name_str:
        return ""
    idx = name_str.rfind("-")
    if idx != -1:
        return name_str[:idx].strip()
    return name_str.strip()


def parse_timings(time_str: str | None) -> str | None:
    if not time_str:
        return None
    encoded: list[str] = []
    for part in time_str.split(","):
        trimmed = part.strip()
        if not trimmed:
            continue
        match = TIMING_RE.search(trimmed)
        if not match:
            continue
        days_str, start, end = match.group(1), match.group(2), match.group(3)

        def fmt(t: str) -> str:
            h, m = t.split(":")
            return f"{int(h):02d}{m}"

        st, et = fmt(start), fmt(end)
        parsed_days: list[str] = []
        i = 0
        while i < len(days_str):
            if i + 1 < len(days_str) and days_str[i : i + 2] == "Th":
                parsed_days.append("Th")
                i += 2
            else:
                parsed_days.append(days_str[i])
                i += 1
        for d in parsed_days:
            if d in DAYS_MAP:
                encoded.append(f"{DAYS_MAP[d]}{st}{et}")
    return ",".join(encoded) if encoded else None


def parse_csv_line(line: str) -> list[str]:
    row: list[str] = []
    cur = ""
    in_quotes = False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            row.append(cur)
            cur = ""
        else:
            cur += ch
    row.append(cur)
    return [c.strip() for c in row]


def parse_courses_from_csv(csv_path: str | Path, semester_code: str) -> list[dict[str, Any]]:
    raw = Path(csv_path).read_text(encoding="utf-8", errors="replace")
    courses: list[dict[str, Any]] = []

    for line in raw.splitlines():
        if not line.strip():
            continue
        row = parse_csv_line(line)
        s_no = (row[0] if row else "").strip()
        if not s_no.isdigit():
            continue

        raw_course_name = (row[1] if len(row) > 1 else "").strip()
        units_idx = next(
            (i for i, col in enumerate(row) if UNITS_RE.match(col.strip())),
            -1,
        )
        if units_idx == -1:
            units_idx = 5 if len(row) > 5 else -1
        units = row[units_idx].strip() if units_idx != -1 else "0-0-0"

        email_idx = -1
        start_search = units_idx + 1 if units_idx != -1 else 2
        for i in range(start_search, len(row)):
            if "@" in row[i]:
                email_idx = i
                break

        lecture_str = tutorial_str = practical_str = ""
        if email_idx != -1:
            vacancy_idx = len(row) - 2
            if vacancy_idx > email_idx + 1:
                timing_cols = row[email_idx + 1 : vacancy_idx]
                if len(timing_cols) >= 1:
                    lecture_str = timing_cols[0].strip()
                if len(timing_cols) >= 2:
                    tutorial_str = timing_cols[1].strip()
                if len(timing_cols) >= 3:
                    practical_str = (
                        timing_cols[2].strip()
                        if len(timing_cols) == 3
                        else timing_cols[3].strip()
                    )
        elif units_idx == 5 and len(row) > 13:
            lecture_str = row[10].strip()
            tutorial_str = row[11].strip()
            practical_str = row[13].strip()
        elif units_idx == 4 and len(row) > 8:
            lecture_str = row[8].strip()
            if len(row) > 9:
                tutorial_str = row[9].strip()
            if len(row) > 10:
                practical_str = row[10].strip()

        code = clean_course_code(raw_course_name)
        name = extract_course_name(raw_course_name)
        if not code:
            continue

        slot_name = "X"
        if len(row) > 3:
            candidate = row[3].strip()
            if len(candidate) <= 2:
                slot_name = candidate
        if slot_name == "X" and units_idx != -1:
            if (
                units_idx - 1 >= 0
                and len(row[units_idx - 1].strip()) <= 2
                and row[units_idx - 1].strip()
            ):
                slot_name = row[units_idx - 1].strip()
            elif (
                units_idx - 2 >= 0
                and len(row[units_idx - 2].strip()) <= 2
                and row[units_idx - 2].strip()
            ):
                slot_name = row[units_idx - 2].strip()

        instructor = (
            row[email_idx - 1].strip() if email_idx != -1 and email_idx > 0 else "N/A"
        )
        instructor_email = (
            (row[email_idx] or "").strip().lower() if email_idx != -1 else None
        )
        current_strength = row[-1].strip() if row else "N/A"

        courses.append(
            attach_instructors(
                {
                    "courseCode": code,
                    "courseName": name,
                    "semesterCode": semester_code,
                    "totalCredits": parse_credit_structure(units),
                    "creditStructure": units,
                    "instructor": instructor,
                    "instructorEmail": (
                        instructor_email if instructor_email and "@" in instructor_email else None
                    ),
                    "currentStrength": current_strength,
                    "slot": {
                        "name": slot_name or "X",
                        "lectureTiming": parse_timings(lecture_str),
                        "lectureTimingStr": lecture_str,
                        "tutorialTiming": parse_timings(tutorial_str),
                        "labTiming": parse_timings(practical_str),
                    },
                    "lectureHall": None,
                }
            )
        )

    resolve_instructor_emails(courses)
    return courses

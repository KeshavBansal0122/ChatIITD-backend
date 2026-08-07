"""IITD semester code helpers — port of Classgrid semester_code_meta.js."""

from __future__ import annotations

from datetime import date


def semester_meta_from_code(code: str) -> dict:
    """
    IITD semester codes (YYTT): YY is shared across both terms in a cycle.
    01 → Semester 1, Jul of 20YY
    02 → Semester 2, Jan of 20(YY+1)
    """
    normalized = (code or "").strip()
    if not normalized.isdigit() or len(normalized) != 4:
        raise ValueError(f"Invalid semester code: {code}")

    yy = int(normalized[:2])
    term = normalized[2:]
    start_year = 2000 + yy

    if term == "01":
        return {
            "label": f"Semester 1, {start_year}–{start_year + 1}",
            "classes_start": date(start_year, 7, 23),
            "last_teaching_day": date(start_year, 11, 17),
        }
    if term == "02":
        spring_year = start_year + 1
        return {
            "label": f"Semester 2, {start_year}–{spring_year}",
            "classes_start": date(spring_year, 1, 6),
            "last_teaching_day": date(spring_year, 5, 15),
        }
    return {
        "label": f"Semester {term}, {start_year}",
        "classes_start": date(start_year, 1, 1),
        "last_teaching_day": date(start_year, 12, 31),
    }

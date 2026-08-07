"""IITD student kerberos helpers — port of Classgrid student_kerberos.js."""

from __future__ import annotations

import re

# aa1234567 (2 letters + 7 digits) or abc123456 (3 letters + 6 digits)
STUDENT_KERBEROS_RE = re.compile(r"^(?:[a-z]{2}[0-9]{7}|[a-z]{3}[0-9]{6})$")


def normalize_kerberos(kerberos: str | None) -> str:
    return (kerberos or "").lower().strip()


def is_student_kerberos(kerberos: str | None) -> bool:
    return bool(STUDENT_KERBEROS_RE.match(normalize_kerberos(kerberos)))


def filter_student_enrollment_data(
    student_courses: dict, course_students: dict
) -> tuple[dict, dict, int]:
    """Drop staff/professor kerberos from LDAP enrollment exports."""
    filtered_student_courses: dict = {}
    skipped = 0
    for kerberos, course_list in (student_courses or {}).items():
        kid = normalize_kerberos(kerberos)
        if not is_student_kerberos(kid):
            skipped += 1
            continue
        filtered_student_courses[kid] = course_list

    filtered_course_students: dict = {}
    for course_code, roster in (course_students or {}).items():
        filtered_course_students[course_code] = [
            row for row in (roster or []) if row and is_student_kerberos(row.get("id"))
        ]

    return filtered_student_courses, filtered_course_students, skipped

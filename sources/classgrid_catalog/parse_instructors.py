"""Instructor parsing helpers — port of Classgrid server/src/parse_instructors.js."""

from __future__ import annotations

from typing import Any


def normalize_name(name: str | None) -> str:
    return " ".join((name or "").split()).strip().upper()


def normalize_email(email: str | None) -> str | None:
    e = (email or "").strip().lower()
    return e if "@" in e else None


def split_instructor_names(raw: str | None) -> list[str]:
    if not raw or raw == "N/A":
        return []
    return [
        " ".join(part.split()).strip()
        for part in raw.split(",")
        if " ".join(part.split()).strip()
    ]


def parse_instructors_from_row(
    instructor_raw: str | None, email_raw: str | None
) -> list[dict[str, str | None]]:
    names = split_instructor_names(instructor_raw)
    primary_email = normalize_email(email_raw)
    if not names:
        if primary_email:
            return [
                {
                    "name": (instructor_raw or "").strip() or primary_email,
                    "email": primary_email,
                }
            ]
        return []
    return [
        {"name": name, "email": primary_email if index == 0 else None}
        for index, name in enumerate(names)
    ]


def sync_primary_instructor_fields(course: dict[str, Any]) -> None:
    instructors = course.get("instructors") or []
    primary = next((i for i in instructors if i.get("email")), None) or (
        instructors[0] if instructors else None
    )
    course["instructor"] = (primary or {}).get("name") or course.get("instructor") or "N/A"
    course["instructorEmail"] = (primary or {}).get("email") or None


def attach_instructors(course: dict[str, Any]) -> dict[str, Any]:
    course["instructors"] = parse_instructors_from_row(
        course.get("instructor"), course.get("instructorEmail")
    )
    sync_primary_instructor_fields(course)
    return course


def resolve_instructor_emails(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill missing co-instructor emails using sole-instructor rows in the batch."""
    email_by_name: dict[str, str] = {}
    for course in courses:
        for inst in course.get("instructors") or []:
            if inst.get("email") and inst.get("name"):
                key = normalize_name(inst["name"])
                email_by_name.setdefault(key, inst["email"])

    for course in courses:
        for inst in course.get("instructors") or []:
            if not inst.get("email") and inst.get("name"):
                inst["email"] = email_by_name.get(normalize_name(inst["name"]))
        sync_primary_instructor_fields(course)
    return courses


def instructors_from_course_data(course_data: dict[str, Any] | None) -> list[dict[str, str | None]]:
    if not course_data or not isinstance(course_data, dict):
        return []
    raw = course_data.get("instructors")
    if isinstance(raw, list) and raw:
        out: list[dict[str, str | None]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            email = normalize_email(item.get("email"))
            if name or email:
                out.append({"name": name, "email": email})
        return out
    return parse_instructors_from_row(
        course_data.get("instructor"), course_data.get("instructorEmail")
    )

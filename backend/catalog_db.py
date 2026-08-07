"""
Query helpers for Classgrid-compatible catalog tables (semesters / catalog_courses).

Instructors are stored inside course_data JSONB — there is no separate professors table
(matches Classgrid). Use search_instructors / get_instructor_offerings for lookups.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlmodel import text

from .models import get_session

logger = logging.getLogger(__name__)


def list_semesters() -> List[Dict[str, Any]]:
    try:
        with get_session() as sess:
            result = sess.execute(
                text(
                    """
                    SELECT s.code, s.label, s.is_active,
                           (SELECT COUNT(*) FROM catalog_courses c
                            WHERE c.semester_code = s.code) AS catalog_count
                    FROM semesters s
                    ORDER BY s.code DESC
                    """
                )
            )
            return [
                {
                    "code": r["code"],
                    "label": r["label"],
                    "is_active": r["is_active"],
                    "catalog_count": r["catalog_count"],
                }
                for r in result.mappings().all()
            ]
    except Exception as e:
        logger.error("[list_semesters] %s", e)
        return []


def get_active_semester_code() -> Optional[str]:
    try:
        with get_session() as sess:
            row = sess.execute(
                text("SELECT code FROM semesters WHERE is_active = true LIMIT 1")
            ).first()
            return row[0] if row else None
    except Exception as e:
        logger.error("[get_active_semester_code] %s", e)
        return None


def get_catalog_offerings_for_codes(codes: List[str]) -> List[Dict[str, Any]]:
    """All historical offerings for the given course codes from catalog_courses."""
    upper = [c.upper() for c in codes]
    if not upper:
        return []
    placeholders = ", ".join(f":c{i}" for i in range(len(upper)))
    params = {f"c{i}": code for i, code in enumerate(upper)}
    try:
        with get_session() as sess:
            result = sess.execute(
                text(
                    f"""
                    SELECT c.semester_code, c.course_code, c.course_data, s.label, s.is_active
                    FROM catalog_courses c
                    JOIN semesters s ON s.code = c.semester_code
                    WHERE c.course_code IN ({placeholders})
                    ORDER BY c.semester_code DESC, c.course_code
                    """
                ),
                params,
            )
            out: List[Dict[str, Any]] = []
            for r in result.mappings().all():
                d = r["course_data"] or {}
                out.append(
                    {
                        "course_code": r["course_code"],
                        "semester_code": r["semester_code"],
                        "label": r["label"],
                        "is_active": r["is_active"],
                        "course_name": d.get("courseName"),
                        "instructor": d.get("instructor"),
                        "instructor_email": d.get("instructorEmail"),
                        "instructors": d.get("instructors") or [],
                        "credits": d.get("totalCredits"),
                        "credit_structure": d.get("creditStructure"),
                        "slot": (d.get("slot") or {}).get("name"),
                        "year": _year_from_semester_code(r["semester_code"]),
                        "semester": _term_from_semester_code(r["semester_code"]),
                    }
                )
            return out
    except Exception as e:
        logger.error("[get_catalog_offerings_for_codes] %s", e)
        return []


def search_instructors(q: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search instructors by name or email across catalog history."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    try:
        with get_session() as sess:
            result = sess.execute(
                text(
                    """
                    SELECT
                        lower(inst->>'email') AS email,
                        (array_agg(inst->>'name' ORDER BY length(inst->>'name') DESC))[1] AS name,
                        COUNT(*)::int AS offering_count
                    FROM catalog_courses c,
                         jsonb_array_elements(
                            CASE
                                WHEN jsonb_typeof(c.course_data->'instructors') = 'array'
                                     AND jsonb_array_length(c.course_data->'instructors') > 0
                                THEN c.course_data->'instructors'
                                ELSE jsonb_build_array(
                                    jsonb_build_object(
                                        'name', c.course_data->>'instructor',
                                        'email', c.course_data->>'instructorEmail'
                                    )
                                )
                            END
                         ) AS inst
                    WHERE (inst->>'email') IS NOT NULL
                      AND (inst->>'email') <> ''
                      AND (
                            lower(inst->>'name') LIKE lower(:pat)
                         OR lower(inst->>'email') LIKE lower(:pat)
                      )
                    GROUP BY lower(inst->>'email')
                    ORDER BY offering_count DESC, name
                    LIMIT :lim
                    """
                ),
                {"pat": f"%{q}%", "lim": limit},
            )
            return [
                {
                    "name": r["name"],
                    "email": r["email"],
                    "offering_count": r["offering_count"],
                }
                for r in result.mappings().all()
            ]
    except Exception as e:
        logger.error("[search_instructors] %s", e)
        return []


def _year_from_semester_code(code: str) -> Optional[str]:
    if not code or len(code) != 4 or not code.isdigit():
        return None
    yy = int(code[:2])
    start = 2000 + yy
    return f"{start}-{str(start + 1)[2:]}"


def _term_from_semester_code(code: str) -> Optional[int]:
    if not code or len(code) != 4:
        return None
    term = code[2:]
    if term == "01":
        return 1
    if term == "02":
        return 2
    return None


def get_student_enrollments(kerberos: str) -> List[Dict[str, Any]]:
    """Return catalog-enriched offerings for a student kerberos across all semesters."""
    kid = (kerberos or "").lower().strip()
    if not kid:
        return []
    try:
        with get_session() as sess:
            result = sess.execute(
                text(
                    """
                    SELECT s.code AS semester_code, s.label, s.is_active,
                           c.course_code, c.course_data
                    FROM student_enrollments e
                    JOIN catalog_courses c
                      ON c.semester_code = e.semester_code
                     AND c.course_code = e.course_code
                    JOIN semesters s ON s.code = e.semester_code
                    WHERE lower(e.kerberos) = :kid
                    ORDER BY s.code DESC, c.course_code
                    """
                ),
                {"kid": kid},
            )
            out: List[Dict[str, Any]] = []
            for r in result.mappings().all():
                d = r["course_data"] or {}
                out.append(
                    {
                        "semester_code": r["semester_code"],
                        "label": r["label"],
                        "is_active": r["is_active"],
                        "course_code": r["course_code"],
                        "course_name": d.get("courseName"),
                        "instructor": d.get("instructor"),
                        "instructor_email": d.get("instructorEmail"),
                        "instructors": d.get("instructors") or [],
                        "credits": d.get("totalCredits"),
                        "slot": (d.get("slot") or {}).get("name"),
                    }
                )
            return out
    except Exception as e:
        logger.error("[get_student_enrollments] %s", e)
        return []


def get_course_roster(course_code: str, semester_code: Optional[str] = None) -> List[Dict[str, str]]:
    """Return roster rows for a course (optionally scoped to a semester)."""
    cc = (course_code or "").upper().strip()
    if not cc:
        return []
    try:
        with get_session() as sess:
            if semester_code:
                result = sess.execute(
                    text(
                        """
                        SELECT student_kerberos, student_name
                        FROM course_rosters
                        WHERE semester_code = :sem AND course_code = :cc
                        ORDER BY student_kerberos
                        """
                    ),
                    {"sem": semester_code, "cc": cc},
                )
            else:
                active = get_active_semester_code()
                if not active:
                    return []
                result = sess.execute(
                    text(
                        """
                        SELECT student_kerberos, student_name
                        FROM course_rosters
                        WHERE semester_code = :sem AND course_code = :cc
                        ORDER BY student_kerberos
                        """
                    ),
                    {"sem": active, "cc": cc},
                )
            return [
                {"id": r["student_kerberos"], "name": r["student_name"] or ""}
                for r in result.mappings().all()
            ]
    except Exception as e:
        logger.error("[get_course_roster] %s", e)
        return []


def enrollment_stats() -> Dict[str, Any]:
    try:
        with get_session() as sess:
            rows = sess.execute(
                text(
                    """
                    SELECT semester_code,
                           COUNT(*)::int AS enrollment_rows,
                           COUNT(DISTINCT kerberos)::int AS students
                    FROM student_enrollments
                    GROUP BY semester_code
                    ORDER BY semester_code DESC
                    """
                )
            ).mappings().all()
            return {
                "by_semester": [dict(r) for r in rows],
                "total_enrollment_rows": sum(r["enrollment_rows"] for r in rows),
                "semesters_with_data": len(rows),
            }
    except Exception as e:
        logger.error("[enrollment_stats] %s", e)
        return {"by_semester": [], "total_enrollment_rows": 0, "semesters_with_data": 0}
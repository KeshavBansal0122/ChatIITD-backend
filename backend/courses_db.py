"""
Centralized access to the course catalogue stored in PostgreSQL.

This module is the single point of contact for all course-related queries.
The original courses.sqlite file is kept at /backend/courses.sqlite as a
backup/seed source only — all runtime queries go through this module via
the shared PostgreSQL database.

Do NOT open courses.sqlite or import sqlite3 anywhere else in the codebase.
"""

import json
import logging
from typing import List, Dict, Optional

from sqlmodel import select, text

from .models import Course, CourseOffering, CourseOverlap, get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Course validation / search (used by crud.py and main.py API endpoints)
# ---------------------------------------------------------------------------

def validate_course_code(course_code: str) -> bool:
    """
    Check whether a course code exists in the database.

    Args:
        course_code: Course code to validate (e.g. "COL100")

    Returns:
        True if the course exists, False otherwise
    """
    try:
        with get_session() as sess:
            result = sess.get(Course, course_code.upper())
            return result is not None
    except Exception as e:
        logger.error(f"[validate_course_code] Error: {e}")
        return False


def search_courses_by_prefix(prefix: str, limit: int = 20) -> List[Dict]:
    """
    Search courses by code prefix for autocomplete.

    Args:
        prefix: Course code prefix (e.g. "COL")
        limit: Maximum number of results to return

    Returns:
        List of dicts with keys 'code' and 'name'
    """
    try:
        with get_session() as sess:
            stmt = (
                select(Course)
                .where(Course.code.startswith(prefix.upper()))  # type: ignore[attr-defined]
                .order_by(Course.code)
                .limit(limit)
            )
            results = sess.exec(stmt).all()
            return [{"code": c.code, "name": c.name} for c in results]
    except Exception as e:
        logger.error(f"[search_courses_by_prefix] Error: {e}")
        return []


# ---------------------------------------------------------------------------
# Course data retrieval (used by agent tools)
# ---------------------------------------------------------------------------

def get_courses_by_codes(codes: List[str]) -> List[Dict]:
    """
    Fetch full course records for a list of course codes.

    Returns:
        List of course dicts
    """
    upper_codes = [c.upper() for c in codes]
    try:
        with get_session() as sess:
            stmt = select(Course).where(Course.code.in_(upper_codes))  # type: ignore[attr-defined]
            courses = sess.exec(stmt).all()
            return [
                {
                    "code": c.code,
                    "name": c.name,
                    "description": c.description,
                    "credits": c.credits,
                    "hours": {
                        "lecture": c.hours_lecture,
                        "tutorial": c.hours_tutorial,
                        "practical": c.hours_practical,
                    },
                    "prereqs": c.prereq,
                    "overlap": c.overlap,
                }
                for c in courses
            ]
    except Exception as e:
        logger.error(f"[get_courses_by_codes] Error: {e}")
        return []


def get_offerings_for_codes(codes: List[str]) -> List[Dict]:
    """
    Fetch all offerings for the given course codes.

    Prefers Classgrid-format `catalog_courses` when populated; falls back to
    legacy `courseoffering` rows.
    """
    from . import catalog_db

    catalog = catalog_db.get_catalog_offerings_for_codes(codes)
    if catalog:
        return [
            {
                "course_code": o["course_code"],
                "year": o.get("year"),
                "semester": o.get("semester"),
                "semester_code": o.get("semester_code"),
                "instructor": o.get("instructor"),
                "instructor_email": o.get("instructor_email"),
                "instructors": o.get("instructors") or [],
                "slot": o.get("slot"),
                "course_name": o.get("course_name"),
            }
            for o in catalog
        ]

    upper_codes = [c.upper() for c in codes]
    try:
        with get_session() as sess:
            stmt = select(CourseOffering).where(
                CourseOffering.code.in_(upper_codes)  # type: ignore[attr-defined]
            )
            offerings = sess.exec(stmt).all()
            return [
                {
                    "course_code": o.code,
                    "year": o.year,
                    "semester": o.semester,
                    "instructor": o.instructor or o.coordinator,
                }
                for o in offerings
            ]
    except Exception as e:
        logger.error(f"[get_offerings_for_codes] Error: {e}")
        return []


# ---------------------------------------------------------------------------
# Arbitrary SELECT queries against the course catalogue (used by the LLM tool)
# ---------------------------------------------------------------------------

# Map of SQLite / logical table names to PostgreSQL table names
_TABLE_MAP = {
    "courses": "course",
    "offerings": "courseoffering",
    "overlaps": "courseoverlap",
    "catalog_courses": "catalog_courses",
    "semesters": "semesters",
}


def run_select_query(query: str) -> str:
    """
    Execute an arbitrary SELECT query against the course catalogue tables in
    PostgreSQL and return results as a JSON string.

    Table name mapping (SQLite → PostgreSQL):
        courses   → course
        offerings → courseoffering
        overlaps  → courseoverlap

    Only SELECT statements are permitted.

    Returns:
        JSON-encoded list of result rows (dicts), or an error message string
    """
    stripped = query.strip()
    if not stripped.lower().startswith("select"):
        return "Invalid. Only SELECT queries are allowed."

    # Rewrite legacy SQLite table names to PostgreSQL names
    rewritten = stripped
    for sqlite_name, pg_name in _TABLE_MAP.items():
        # Replace whole-word occurrences (case-insensitive)
        import re
        rewritten = re.sub(
            rf"\b{sqlite_name}\b", pg_name, rewritten, flags=re.IGNORECASE
        )

    try:
        with get_session() as sess:
            result = sess.exec(text(rewritten))  # type: ignore[arg-type]
            rows = result.fetchall()
            keys = list(result.keys())
            data = [dict(zip(keys, row)) for row in rows]
            logger.debug(f"[run_select_query] Returned {len(data)} rows")
            return json.dumps(data)
    except Exception as e:
        logger.error(f"[run_select_query] Error: {e}")
        return f"An error occurred: {str(e)}"

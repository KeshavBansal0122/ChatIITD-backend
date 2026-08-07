"""
Sync LDAP student_enrollments → usercourse (programme semester 1–10).

Also upserts lightweight user stubs (email = kerberos@iitd.ac.in) so courses
are ready before first OIDC login; login merges via email/kerberos.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlmodel import select, text

from . import models
from .models import get_session

logger = logging.getLogger(__name__)

STUDENT_KERBEROS_RE = re.compile(r"^(?:[a-z]{2}[0-9]{7}|[a-z]{3}[0-9]{6})$")


def parse_year_of_joining(kerberos: str | None) -> Optional[int]:
    """
    Derive entry year from kerberos (matches Classgrid kerberosMeta).

    Branch/programme = first 3 alphanumeric chars; year = next 2 digits → 20YY.
    Examples: mt6240685 → 2024, me2241111 → 2024, phz248290 → 2024.
    """
    if not kerberos:
        return None
    k = kerberos.lower().strip()
    if not STUDENT_KERBEROS_RE.match(k):
        return None
    m = re.match(r"^[a-z0-9]{3}([0-9]{2})", k)
    if not m:
        return None
    try:
        year = 2000 + int(m.group(1))
    except ValueError:
        return None
    # Reject absurd parses (e.g. leftover 2+7 mistakes like year 2062)
    if year < 2010 or year > 2035:
        return None
    return year


def yytt_to_programme_semester(semester_code: str, year_of_joining: int) -> Optional[int]:
    """Map IITD YYTT code to programme semester index 1–10."""
    code = (semester_code or "").strip()
    if len(code) != 4 or not code.isdigit():
        return None
    yy = int(code[:2])
    term = code[2:]
    join_yy = year_of_joining - 2000
    offset = yy - join_yy
    if term == "01":
        sem = offset * 2 + 1
    elif term == "02":
        sem = offset * 2 + 2
    else:
        # Summer / special — map after spring of same YY cycle
        sem = offset * 2 + 2
    if sem < 1 or sem > 10:
        return None
    return sem


def get_active_semester_code() -> Optional[str]:
    with get_session() as sess:
        row = sess.execute(
            text("SELECT code FROM semesters WHERE is_active = true LIMIT 1")
        ).first()
        return row[0] if row else None


def enrollments_for_kerberos(
    kerberos: str,
    *,
    exclude_active: bool = True,
) -> Dict[int, List[str]]:
    """Return {programme_semester: [course_codes]} from student_enrollments."""
    kid = kerberos.lower().strip()
    year = parse_year_of_joining(kid)
    if year is None:
        return {}

    active = get_active_semester_code() if exclude_active else None
    with get_session() as sess:
        rows = sess.execute(
            text(
                """
                SELECT semester_code, course_code
                FROM student_enrollments
                WHERE lower(kerberos) = :kid
                ORDER BY semester_code, course_code
                """
            ),
            {"kid": kid},
        ).all()

    by_sem: Dict[int, List[str]] = defaultdict(list)
    seen: set[Tuple[int, str]] = set()
    for semester_code, course_code in rows:
        if active and semester_code == active:
            continue
        sem = yytt_to_programme_semester(semester_code, year)
        if sem is None:
            continue
        code = (course_code or "").upper().strip()
        if not code or (sem, code) in seen:
            continue
        seen.add((sem, code))
        by_sem[sem].append(code)
    return dict(by_sem)


def ensure_user_stub(kerberos: str, name: str = "", hostel: str | None = None) -> Optional[models.User]:
    """Create or return a user row for an LDAP student (no oauth until login)."""
    kid = kerberos.lower().strip()
    if not STUDENT_KERBEROS_RE.match(kid):
        return None
    email = f"{kid}@iitd.ac.in"
    with get_session() as sess:
        existing = sess.exec(
            select(models.User).where(
                (models.User.kerberos == kid) | (models.User.email == email)
            )
        ).first()
        if existing:
            changed = False
            if not existing.kerberos:
                existing.kerberos = kid
                changed = True
            if name and (not existing.name or existing.name == kid):
                existing.name = name
                changed = True
            if hostel and not existing.hostel:
                existing.hostel = hostel
                changed = True
            if changed:
                sess.add(existing)
                sess.commit()
                sess.refresh(existing)
            return existing

        user = models.User(
            email=email,
            name=name or kid,
            kerberos=kid,
            entry_number=kid.upper(),
            hostel=hostel,
            category="student",
            role="user",
            oauth_id=None,
        )
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        return user


def apply_courses_to_user(
    user_id: int,
    courses_by_semester: Dict[int, List[str]],
    *,
    only_if_empty: bool = True,
) -> int:
    """
    Write courses into usercourse.
    Returns number of rows inserted (0 if skipped).
    """
    if not courses_by_semester:
        return 0
    with get_session() as sess:
        existing = sess.exec(
            select(models.UserCourse).where(models.UserCourse.user_id == user_id)
        ).all()
        if existing and only_if_empty:
            return 0
        if existing and not only_if_empty:
            for uc in existing:
                sess.delete(uc)

        n = 0
        for semester, codes in courses_by_semester.items():
            for code in codes:
                sess.add(
                    models.UserCourse(
                        user_id=user_id,
                        course_code=code,
                        semester=int(semester),
                    )
                )
                n += 1
        sess.commit()
        return n


def seed_user_courses_from_ldap(user: models.User, *, only_if_empty: bool = True) -> int:
    """Seed one user's usercourse from LDAP enrollments (skip if already filled)."""
    if not user.kerberos or user.id is None:
        return 0
    courses = enrollments_for_kerberos(user.kerberos, exclude_active=True)
    return apply_courses_to_user(int(user.id), courses, only_if_empty=only_if_empty)


def sync_all_ldap_enrollments_to_usercourse(
    *,
    create_stubs: bool = True,
    only_if_empty: bool = True,
    exclude_active: bool = True,
) -> dict:
    """
    Bulk sync: optional user stubs + usercourse rows for every LDAP kerberos.
    """
    active = get_active_semester_code() if exclude_active else None
    stats = {
        "students": 0,
        "stubs_created": 0,
        "users_updated": 0,
        "course_rows": 0,
        "skipped_no_year": 0,
        "skipped_has_courses": 0,
    }

    with get_session() as sess:
        # Best display name per kerberos
        name_rows = sess.execute(
            text(
                """
                SELECT lower(student_kerberos) AS kid,
                       (array_agg(student_name ORDER BY length(student_name) DESC))[1] AS name
                FROM course_rosters
                WHERE trim(student_name) <> ''
                GROUP BY lower(student_kerberos)
                """
            )
        ).mappings().all()
        names = {r["kid"]: r["name"] for r in name_rows}

        hostel_rows = sess.execute(
            text("SELECT lower(kerberos) AS kid, hostel FROM students WHERE hostel IS NOT NULL")
        ).mappings().all()
        hostels = {r["kid"]: r["hostel"] for r in hostel_rows}

        enroll_sql = """
            SELECT lower(kerberos) AS kid, semester_code, course_code
            FROM student_enrollments
        """
        if active:
            enroll_sql += " WHERE semester_code <> :active"
            enroll_rows = sess.execute(text(enroll_sql), {"active": active}).all()
        else:
            enroll_rows = sess.execute(text(enroll_sql)).all()

    by_student: Dict[str, Dict[int, List[str]]] = defaultdict(lambda: defaultdict(list))
    seen: set[Tuple[str, int, str]] = set()
    for kid, semester_code, course_code in enroll_rows:
        year = parse_year_of_joining(kid)
        if year is None:
            stats["skipped_no_year"] += 1
            continue
        sem = yytt_to_programme_semester(semester_code, year)
        if sem is None:
            continue
        code = (course_code or "").upper().strip()
        key = (kid, sem, code)
        if not code or key in seen:
            continue
        seen.add(key)
        by_student[kid][sem].append(code)

    stats["students"] = len(by_student)

    for kid, courses_map in by_student.items():
        user = None
        if create_stubs:
            before_ids = None
            with get_session() as sess:
                before = sess.exec(
                    select(models.User).where(
                        (models.User.kerberos == kid)
                        | (models.User.email == f"{kid}@iitd.ac.in")
                    )
                ).first()
                before_ids = before.id if before else None
            user = ensure_user_stub(kid, names.get(kid, ""), hostels.get(kid))
            if user and before_ids is None:
                stats["stubs_created"] += 1
        else:
            with get_session() as sess:
                user = sess.exec(
                    select(models.User).where(models.User.kerberos == kid)
                ).first()

        if not user or user.id is None:
            continue

        n = apply_courses_to_user(
            int(user.id),
            {int(s): codes for s, codes in courses_map.items()},
            only_if_empty=only_if_empty,
        )
        if n == 0:
            stats["skipped_has_courses"] += 1
        else:
            stats["users_updated"] += 1
            stats["course_rows"] += n

    logger.info("LDAP→usercourse sync: %s", stats)
    return stats

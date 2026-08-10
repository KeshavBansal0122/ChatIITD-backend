"""
Database models for the ChatIITD application.

Supports both SQLite (development) and PostgreSQL (production).
"""

from typing import Optional, Any, Dict
from datetime import datetime, date
import os
import sqlite3
import logging
from pathlib import Path
from sqlalchemy import Column, Text, Date, DateTime, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel, Field, create_engine, Session, select, text

# Database URL - defaults to PostgreSQL for development with docker-compose
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://chatiitd:chatiitd_dev@localhost:5432/chatiitd"
)


class User(SQLModel, table=True):
    """User account linked to IITD OAuth."""
    id: Optional[int] = Field(default=None, primary_key=True)
    oauth_id: Optional[str] = Field(default=None, index=True)  # IITD OAuth subject ID
    email: str = Field(index=True)
    name: Optional[str] = None
    picture: Optional[str] = None
    role: str = Field(default="user")  # "user" or "admin"
    # IITD OAuth fields
    hostel: Optional[str] = None
    kerberos: Optional[str] = Field(default=None, index=True)
    entry_number: Optional[str] = None
    department: Optional[str] = None
    category: Optional[str] = None  # "student", "faculty", etc.


class OAuthState(SQLModel, table=True):
    """Temporary storage for PKCE code_verifier during OAuth flow."""
    state: str = Field(primary_key=True)
    code_verifier: str
    redirect_uri: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserCourse(SQLModel, table=True):
    """Courses completed by a user, organized by semester."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    course_code: str
    semester: int  # 1-10 (supports dual degrees)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Document(SQLModel, table=True):
    """Admin-uploaded PDF documents."""
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str  # stored filename on disk
    original_name: str  # user-visible name
    description: str = Field(default="")
    file_size: int = 0
    chunk_count: int = 0
    uploaded_by: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Chat(SQLModel, table=True):
    """Chat session belonging to a user."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    title: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Message(SQLModel, table=True):
    """User-visible messages in a chat (simplified view)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    sender: str  # "user" or "assistant"
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MessageHistory(SQLModel, table=True):
    """
    Full conversation history for the agent (includes tool calls).
    
    This stores the complete OpenAI message format including tool_calls and tool results
    which are needed for the agent's context but not shown to users.
    """
    __tablename__ = "message_history"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)  # Maps to chat.id
    role: str  # "user", "assistant", "tool", "system"
    content: Optional[str] = None
    tool_calls: Optional[str] = None  # JSON string of tool calls
    tool_call_id: Optional[str] = None  # For tool response messages
    name: Optional[str] = None  # Tool name for tool messages
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Course catalogue tables (migrated from courses.sqlite)
# ---------------------------------------------------------------------------

class Course(SQLModel, table=True):
    """IITD course catalogue entry."""
    code: str = Field(primary_key=True)  # e.g. "COL100" or "COL1000"
    name: Optional[str] = None
    description: Optional[str] = None
    hours_lecture: Optional[float] = None
    hours_tutorial: Optional[float] = None
    hours_practical: Optional[float] = None
    credits: Optional[float] = None
    prereq: Optional[str] = None   # raw text from source
    overlap: Optional[str] = None  # raw text from source
    # curriculum generation: legacy (entry ≤2024) | 2025 (entry ≥2025)
    generation: Optional[str] = Field(default="legacy", index=True)
    academic_unit: Optional[str] = None
    learning_outcomes: Optional[Any] = Field(default=None, sa_column=Column(JSONB))
    source: Optional[str] = None  # sqlite | curriculum_web | pdf
    source_url: Optional[str] = None


class Programme(SQLModel, table=True):
    """Degree programme template for a curriculum generation."""
    __tablename__ = "programme"

    code: str = Field(primary_key=True)
    generation: str = Field(primary_key=True)  # legacy | 2025
    name: Optional[str] = None
    degree_type: Optional[str] = None
    department: Optional[str] = None
    dual: bool = False
    source_url: Optional[str] = None
    raw: Optional[Any] = Field(default=None, sa_column=Column(JSONB))


class ProgrammeCreditReq(SQLModel, table=True):
    __tablename__ = "programme_credit_req"

    id: Optional[int] = Field(default=None, primary_key=True)
    programme_code: str = Field(index=True)
    generation: str = Field(index=True)
    category: str
    label: Optional[str] = None
    credits_or_units: Optional[float] = None
    kind: str = "graded"  # graded | ngu


class ProgrammeBasket(SQLModel, table=True):
    __tablename__ = "programme_basket"

    id: Optional[int] = Field(default=None, primary_key=True)
    programme_code: str = Field(index=True)
    generation: str = Field(index=True)
    basket_id: str
    name: Optional[str] = None
    min_credits: Optional[float] = None
    min_tracks: Optional[int] = None
    rules_text: Optional[str] = None


class ProgrammeCourse(SQLModel, table=True):
    __tablename__ = "programme_course"

    id: Optional[int] = Field(default=None, primary_key=True)
    programme_code: str = Field(index=True)
    generation: str = Field(index=True)
    course_code: str = Field(index=True)
    category: str
    basket_id: Optional[str] = None
    is_core: bool = True


class ProgrammeSemester(SQLModel, table=True):
    __tablename__ = "programme_semester"

    programme_code: str = Field(primary_key=True)
    generation: str = Field(primary_key=True)
    semester: int = Field(primary_key=True)
    entries: Optional[Any] = Field(default=None, sa_column=Column(JSONB))


class ProgrammeOutcome(SQLModel, table=True):
    __tablename__ = "programme_outcome"

    id: Optional[int] = Field(default=None, primary_key=True)
    programme_code: str = Field(index=True)
    generation: str = Field(index=True)
    outcome_id: str
    text: str


class CourseOffering(SQLModel, table=True):
    """A specific semester offering of a course."""
    __tablename__ = "courseoffering"

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True)   # FK → Course.code
    year: Optional[str] = None      # e.g. "2024-25"
    semester: Optional[int] = None  # 1 or 2
    coordinator: Optional[str] = None
    instructor: Optional[str] = None  # from JSONL (may differ from coordinator)
    slot: Optional[str] = None


class CourseOverlap(SQLModel, table=True):
    """Pair of courses that overlap (cannot be taken together)."""
    __tablename__ = "courseoverlap"

    id: Optional[int] = Field(default=None, primary_key=True)
    code_1: str = Field(index=True)
    code_2: str = Field(index=True)


# ---------------------------------------------------------------------------
# Classgrid-compatible catalog (per-semester offerings + instructors in JSONB)
# Applied by db/migrations/001_classgrid_catalog.sql; also created via init_db.
# ---------------------------------------------------------------------------

class Semester(SQLModel, table=True):
    """Academic semester (YYTT code), matching Classgrid `semesters`."""
    __tablename__ = "semesters"

    code: str = Field(primary_key=True)  # e.g. "2601"
    label: str
    classes_start: date = Field(sa_column=Column(Date, nullable=False))
    last_teaching_day: date = Field(sa_column=Column(Date, nullable=False))
    is_active: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default="false"))
    academic_calendar: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    catalog_etag: Optional[str] = None
    catalog_updated_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="now()"),
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="now()"),
    )


class CatalogCourse(SQLModel, table=True):
    """
    Per-semester course offering (Classgrid `catalog_courses`).

    course_data JSONB mirrors Classgrid and includes:
      courseCode, courseName, semesterCode, totalCredits, creditStructure,
      instructor, instructorEmail, instructors[{name,email}], slot{...},
      currentStrength, lectureHall
    """
    __tablename__ = "catalog_courses"
    __table_args__ = (UniqueConstraint("semester_code", "course_code"),)

    semester_code: str = Field(primary_key=True, foreign_key="semesters.code")
    course_code: str = Field(primary_key=True, index=True)
    course_data: Dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))


class StudentEnrollment(SQLModel, table=True):
    """Who took which course in a semester (from IITD LDAP)."""
    __tablename__ = "student_enrollments"

    semester_code: str = Field(primary_key=True, foreign_key="semesters.code")
    kerberos: str = Field(primary_key=True, max_length=64, index=True)
    course_code: str = Field(primary_key=True, index=True)


class CourseRoster(SQLModel, table=True):
    """Per-course student list with display names (from IITD LDAP)."""
    __tablename__ = "course_rosters"

    semester_code: str = Field(primary_key=True, foreign_key="semesters.code")
    course_code: str = Field(primary_key=True, index=True)
    student_kerberos: str = Field(primary_key=True, max_length=64, index=True)
    student_name: str = Field(default="")


class Student(SQLModel, table=True):
    """Optional student profile overlay (hostel). Not the enrollment source of truth."""
    __tablename__ = "students"

    kerberos: str = Field(primary_key=True, max_length=64)
    hostel: Optional[str] = None
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="now()"),
    )


# Engine singleton
_engine = None


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        connect_args = {}
        if DATABASE_URL.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        _engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)
    return _engine


_COURSES_SQLITE = Path(__file__).resolve().parent.parent / "courses.sqlite"
_log = logging.getLogger(__name__)


def _seed_courses_from_sqlite() -> None:
    """
    Populate Course, CourseOffering, and CourseOverlap tables from courses.sqlite.
    Only runs when the Course table is empty. Safe to call on every startup.
    """
    if not _COURSES_SQLITE.exists():
        _log.warning("courses.sqlite not found at %s — skipping course seed", _COURSES_SQLITE)
        return

    with get_session() as sess:
        if sess.exec(select(Course)).first() is not None:
            return  # already seeded

    _log.info("Seeding course catalogue from %s ...", _COURSES_SQLITE)
    conn = sqlite3.connect(f"file:{_COURSES_SQLITE}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    with get_session() as sess:
        # ── Courses ──────────────────────────────────────────────────────────
        rows = conn.execute("SELECT * FROM courses").fetchall()
        for row in rows:
            sess.add(Course(
                code=row["code"],
                name=row["name"],
                description=row["description"],
                hours_lecture=row["hours_lecture"],
                hours_tutorial=row["hours_tutorial"],
                hours_practical=row["hours_practical"],
                credits=row["credits"],
                prereq=row["prereq"],
                overlap=row["overlap"],
                generation="legacy",
                source="sqlite",
            ))
        sess.commit()
        _log.info("  courses: %d rows inserted", len(rows))

        # ── Offerings ────────────────────────────────────────────────────────
        rows = conn.execute("SELECT * FROM offerings").fetchall()
        for row in rows:
            sess.add(CourseOffering(
                code=(row["code"] or "").upper(),
                year=row["year"] or "",
                semester=row["semester"] or 0,
                coordinator=row["coordinator"],
                instructor=row["coordinator"],  # same source; JSONL merge optional
                slot=row["slot"],
            ))
        sess.commit()
        _log.info("  offerings: %d rows inserted", len(rows))

        # ── Overlaps ─────────────────────────────────────────────────────────
        rows = conn.execute("SELECT * FROM overlaps").fetchall()
        for row in rows:
            sess.add(CourseOverlap(code_1=row["code_1"], code_2=row["code_2"]))
        sess.commit()
        _log.info("  overlaps: %d rows inserted", len(rows))

    conn.close()
    _log.info("Course catalogue seeding complete.")


def init_db():
    """Initialize database tables and seed static data."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _seed_courses_from_sqlite()


def get_session():
    """Get a new database session. Always use this as the single point of DB access."""
    return Session(get_engine())

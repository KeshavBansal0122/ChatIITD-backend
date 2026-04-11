"""
Database models for the ChatIITD application.

Supports both SQLite (development) and PostgreSQL (production).
"""

from typing import Optional
from datetime import datetime
import os
import sqlite3
import logging
from pathlib import Path
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
    code: str = Field(primary_key=True)  # e.g. "COL100"
    name: Optional[str] = None
    description: Optional[str] = None
    hours_lecture: Optional[int] = None
    hours_tutorial: Optional[int] = None
    hours_practical: Optional[int] = None
    credits: Optional[int] = None
    prereq: Optional[str] = None   # raw text from source
    overlap: Optional[str] = None  # raw text from source


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

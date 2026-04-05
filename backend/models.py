"""
Database models for the ChatIITD application.

Supports both SQLite (development) and PostgreSQL (production).
"""

from typing import Optional
from datetime import datetime
import os
from sqlmodel import SQLModel, Field, create_engine, Session, text
from sqlalchemy import Index

# Database URL - defaults to PostgreSQL for development with docker-compose
# For SQLite (legacy): sqlite:///messages.db
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


def init_db():
    """Initialize database tables."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)


def get_session():
    """Get a new database session."""
    return Session(get_engine())


# For backward compatibility
ENGINE = get_engine()

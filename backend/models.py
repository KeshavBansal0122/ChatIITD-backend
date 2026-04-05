from typing import Optional,  List
from datetime import datetime
import os
from sqlmodel import SQLModel, Field, create_engine

# Make the database URL configurable via environment. Default to local sqlite for dev.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///messages.db")


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    oauth_id: Optional[str] = None  # IITD OAuth subject ID (sub claim)
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    role: str = Field(default="user")  # "user" or "admin"
    # IITD OAuth fields
    hostel: Optional[str] = None
    kerberos: Optional[str] = None  # Derived from entry_number
    entry_number: Optional[str] = None  # e.g., "2024ME21111"
    department: Optional[str] = None  # e.g., "Mechanical Engineering"
    category: Optional[str] = None  # e.g., "student", "faculty"


class OAuthState(SQLModel, table=True):
    """Temporary storage for PKCE code_verifier during OAuth flow"""
    state: str = Field(primary_key=True)  # Random state string
    code_verifier: str  # PKCE verifier (43-128 chars)
    redirect_uri: str  # Original redirect URI from client
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Document(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str  # stored filename on disk
    original_name: str  # user-visible name
    description: str = Field(default="")
    file_size: int = 0  # bytes
    chunk_count: int = 0
    uploaded_by: int  # user id of the admin who uploaded
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Chat(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    title: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    

class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int
    sender: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    
def init_db():
    # create engine with SQLite-specific connect args when using sqlite file
    connect_args = {}
    if DATABASE_URL.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)
    SQLModel.metadata.create_all(engine)


# Export a shared engine for CRUD usage
def get_engine():
    connect_args = {}
    if DATABASE_URL.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(DATABASE_URL, echo=False, connect_args=connect_args)

ENGINE = get_engine()

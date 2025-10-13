from typing import Optional
from datetime import datetime
import os
from sqlmodel import SQLModel, Field, create_engine

# Make the database URL configurable via environment. Default to local sqlite for dev.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///messages.db")


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None


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

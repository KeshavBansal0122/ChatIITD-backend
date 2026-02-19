from datetime import datetime
from typing import List
from pydantic import BaseModel


class OIDCToken(BaseModel):
    id_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


class ChatCreate(BaseModel):
    title: str | None = None


class ChatRead(BaseModel):
    id: int
    user_id: int
    title: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    content: str


class MessageRead(BaseModel):
    id: int
    chat_id: int
    sender: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class NewChatResponse(BaseModel):
    """Response for creating a new chat with first message"""
    chat: ChatRead
    message: MessageRead
    title: str


class DocumentRead(BaseModel):
    id: int
    original_name: str
    description: str
    file_size: int
    chunk_count: int
    uploaded_by: int
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentUploadResponse(BaseModel):
    document: DocumentRead
    message: str

from datetime import datetime
from typing import List
from pydantic import BaseModel, Field


class OIDCToken(BaseModel):
    """OIDC token for authentication"""
    id_token: str = Field(..., description="OpenID Connect identity token")


class TokenResponse(BaseModel):
    """Response containing JWT access token"""
    access_token: str = Field(..., description="JWT access token for API authentication")
    token_type: str = Field(default="bearer", description="Token type (always 'bearer')")
    
    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer"
            }
        }


class OAuthCallbackRequest(BaseModel):
    """OAuth callback request payload"""
    code: str = Field(..., description="Authorization code from OAuth provider")
    state: str = Field(..., description="State parameter for CSRF protection")
    
    class Config:
        json_schema_extra = {
            "example": {
                "code": "abc123def456",
                "state": "xyz789"
            }
        }


class OAuthSigninUrlResponse(BaseModel):
    """Response containing OAuth signin URL"""
    signin_url: str = Field(..., description="Complete IITD OAuth authorization URL with PKCE")
    state: str = Field(..., description="State parameter stored server-side with PKCE code_verifier")
    instructions: str = Field(..., description="Instructions for using the signin URL")
    
    class Config:
        json_schema_extra = {
            "example": {
                "signin_url": "https://auth.devclub.in/api/oauth/authorize?response_type=code&client_id=your_client_id&redirect_uri=http://localhost:3000/callback&scope=openid%20profile%20email&state=abc123&code_challenge=xyz789&code_challenge_method=S256",
                "state": "abc123",
                "instructions": "Redirect user to this URL to initiate OAuth flow. The state is stored server-side with PKCE parameters."
            }
        }


class ChatCreate(BaseModel):
    """Request to create a new chat session"""
    title: str | None = Field(default=None, description="Optional title for the chat session")
    
    class Config:
        json_schema_extra = {
            "example": {
                "title": "Discussion about machine learning"
            }
        }


class ChatRead(BaseModel):
    """Chat session details"""
    id: int = Field(..., description="Unique identifier for the chat session")
    user_id: int = Field(..., description="ID of the user who owns this chat")
    title: str | None = Field(description="Title of the chat session")
    created_at: datetime = Field(..., description="Timestamp when the chat was created")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "user_id": 123,
                "title": "Discussion about machine learning",
                "created_at": "2024-01-15T10:30:00Z"
            }
        }


class MessageCreate(BaseModel):
    """Request to create a new message"""
    content: str = Field(..., description="Content of the message to send", min_length=1)
    
    class Config:
        json_schema_extra = {
            "example": {
                "content": "What are the latest developments in AI?"
            }
        }


class MessageRead(BaseModel):
    """Message details"""
    id: int = Field(..., description="Unique identifier for the message")
    chat_id: int = Field(..., description="ID of the chat session this message belongs to")
    sender: str = Field(..., description="Who sent the message ('user' or 'assistant')")
    content: str = Field(..., description="Content of the message")
    created_at: datetime = Field(..., description="Timestamp when the message was created")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "chat_id": 1,
                "sender": "assistant",
                "content": "AI has seen remarkable progress recently, especially in large language models...",
                "created_at": "2024-01-15T10:31:00Z"
            }
        }


class NewChatResponse(BaseModel):
    """Response for creating a new chat with first message"""
    chat: ChatRead = Field(..., description="The created chat session")
    message: MessageRead = Field(..., description="The AI agent's response message")
    title: str = Field(..., description="Generated or provided title for the chat")
    
    class Config:
        json_schema_extra = {
            "example": {
                "chat": {
                    "id": 1,
                    "user_id": 123,
                    "title": "Chat Title",
                    "created_at": "2024-01-15T10:30:00Z"
                },
                "message": {
                    "id": 2,
                    "chat_id": 1,
                    "sender": "assistant",
                    "content": "Hello! I'm here to help you with your questions.",
                    "created_at": "2024-01-15T10:31:00Z"
                },
                "title": "Chat Title"
            }
        }


class DocumentRead(BaseModel):
    """Document metadata"""
    id: int = Field(..., description="Unique identifier for the document")
    original_name: str = Field(..., description="Original filename of the uploaded document")
    description: str = Field(..., description="Admin-provided description of the document")
    file_size: int = Field(..., description="File size in bytes")
    chunk_count: int = Field(..., description="Number of chunks the document was split into")
    uploaded_by: int = Field(..., description="ID of the admin user who uploaded the document")
    created_at: datetime = Field(..., description="Timestamp when the document was uploaded")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "original_name": "machine_learning_handbook.pdf",
                "description": "Comprehensive guide to machine learning algorithms",
                "file_size": 2048576,
                "chunk_count": 45,
                "uploaded_by": 456,
                "created_at": "2024-01-15T09:00:00Z"
            }
        }


class DocumentUploadResponse(BaseModel):
    """Response for successful document upload"""
    document: DocumentRead = Field(..., description="Metadata of the uploaded document")
    message: str = Field(..., description="Success message with processing details")
    
    class Config:
        json_schema_extra = {
            "example": {
                "document": {
                    "id": 1,
                    "original_name": "machine_learning_handbook.pdf",
                    "description": "Comprehensive guide to machine learning algorithms",
                    "file_size": 2048576,
                    "chunk_count": 45,
                    "uploaded_by": 456,
                    "created_at": "2024-01-15T09:00:00Z"
                },
                "message": "Successfully uploaded and indexed 45 chunks"
            }
        }

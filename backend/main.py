from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from agentic_chatbot.agent import invoke_memory_agent

from . import models, crud, schemas, auth, qdrant_service

import os
import uuid
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Uploads directory for admin-uploaded PDFs
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="IITD Agent Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTP bearer handled in auth.get_current_user


@app.on_event("startup")
def on_startup():
    models.init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/callback", response_model=schemas.TokenResponse)
async def auth_callback(payload: schemas.OAuthCallbackRequest):
    """OAuth callback endpoint for DevClub authentication."""
    code = payload.code
    state = payload.state

    # Validate incoming parameters
    print("Auth callback received code:", code, "state:", state)
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state in the request"
        )
    
    # Verify the authorization code with DevClub OAuth server
    user_info = await auth.verify_devclub_code(code, state)
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Error during authentication"
        )
    
    # Get or create user in database
    user = crud.get_or_create_user(user_info)
    print("Authenticated user:", user)
    
    # Create JWT access token
    access_token = auth.create_access_token({"sub": str(user.id)})
    
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/chats", response_model=schemas.ChatRead)
def create_chat(request: schemas.ChatCreate, current_user: models.User = Depends(auth.get_current_user)):
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    chat = crud.create_chat(user_id, request.title)
    return chat


@app.get("/chats", response_model=list[schemas.ChatRead])
def list_chats(current_user: models.User = Depends(auth.get_current_user)):
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    return crud.list_chats(user_id)


@app.get("/chats/{chat_id}", response_model=schemas.ChatRead)
def get_chat(chat_id: int, current_user: models.User = Depends(auth.get_current_user)):
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@app.post("/chats/new", response_model=schemas.NewChatResponse)
def create_new_chat_with_message(message: schemas.MessageCreate, current_user: models.User = Depends(auth.get_current_user)):
    """
    Create a new chat and send the first message.
    Returns the chat, the assistant's response, and the chat title.
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    
    # Hardcoded title for now - do a call to return one later
    title_text = "Chat Title"
    
    # Create the chat with the title
    chat = crud.create_chat(user_id, title_text)
    
    if chat.id is None:
        raise HTTPException(status_code=500, detail="Failed to create chat")
    
    # Store user message
    crud.create_message(chat_id=chat.id, sender="user", content=message.content)
    
    # Build input dict as expected by agent
    agent_input = {"input": message.content}
    # pass session id as chat id to persist history
    try:
        response = invoke_memory_agent(agent_input, session_id=str(chat.id))
        assistant_text = response.get('output') if isinstance(response, dict) else str(response)
        if assistant_text is None:
            assistant_text = ""
    except Exception as e:
        # Log the exception (print for now). In production, integrate structured logging.
        print("Agent invocation failed:", e)
        raise HTTPException(status_code=502, detail="Agent failed to respond")
    
    assistant_msg = crud.create_message(chat_id=chat.id, sender="assistant", content=assistant_text)
    
    return {
        "chat": chat,
        "message": assistant_msg,
        "title": title_text
    }



@app.post("/chats/{chat_id}/messages", response_model=schemas.MessageRead)
def send_message(chat_id: int, message: schemas.MessageCreate, current_user: models.User = Depends(auth.get_current_user)):
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")

    # store user message
    crud.create_message(chat_id=chat_id, sender="user", content=message.content)


    # Build input dict as expected by agent
    agent_input = {"input": message.content}
    # pass session id as chat id to persist history
    try:
        response = invoke_memory_agent(agent_input, session_id=str(chat_id))
        assistant_text = response.get('output') if isinstance(response, dict) else str(response)
        if assistant_text is None:
            assistant_text = ""
    except Exception as e:
        # Log the exception (print for now). In production, integrate structured logging.
        print("Agent invocation failed:", e)
        raise HTTPException(status_code=502, detail="Agent failed to respond")

    assistant_msg = crud.create_message(chat_id=chat_id, sender="assistant", content=assistant_text)
    return assistant_msg


@app.get("/chats/{chat_id}/messages", response_model=list[schemas.MessageRead])
def get_messages(chat_id: int, current_user: models.User = Depends(auth.get_current_user)):
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return crud.list_messages(chat_id)

@app.delete("/chats/{chat_id}", status_code=204)
def delete_chat_endpoint(chat_id: int, current_user: models.User = Depends(auth.get_current_user)):
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    crud.delete_chat(chat_id)
    return {"detail": "Chat deleted"}


# ============================================================
# Admin – Document Management Routes
# ============================================================


@app.post("/admin/documents", response_model=schemas.DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    description: str = Form(""),
    current_user: models.User = Depends(auth.get_current_admin),
):
    """Upload a PDF, chunk it, embed chunks and store in Qdrant.

    - **file**: PDF file (application/pdf)
    - **description**: Admin-supplied description for this document
    """
    # Validate file type
    if file.content_type not in ("application/pdf",):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted",
        )

    # Save PDF to disk
    original_name = file.filename or "untitled.pdf"
    stored_name = f"{uuid.uuid4().hex}_{original_name}"
    dest_path = UPLOADS_DIR / stored_name

    contents = await file.read()
    file_size = len(contents)
    dest_path.write_bytes(contents)

    # Chunk the PDF
    try:
        # Import the chunker from the chunking package
        import sys
        chunking_dir = str(Path(__file__).resolve().parent.parent / "chunking")
        if chunking_dir not in sys.path:
            sys.path.insert(0, chunking_dir)
        from pdf_chunker import PDFSectionChunker

        chunker = PDFSectionChunker()
        payloads = chunker.process_pdf(str(dest_path))
    except Exception as e:
        # Clean up the saved file on failure
        dest_path.unlink(missing_ok=True)
        logger.error("PDF chunking failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to chunk PDF: {e}",
        )

    # Create the Document row first so we get an id
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")

    doc = crud.create_document(
        filename=stored_name,
        original_name=original_name,
        description=description,
        file_size=file_size,
        chunk_count=len(payloads),
        uploaded_by=int(current_user.id),
    )

    # Embed and upsert to Qdrant
    try:
        from datetime import datetime

        qdrant_service.upsert_chunks(
            file_id=int(doc.id),  # type: ignore[arg-type]
            file_name=original_name,
            description=description,
            upload_date=datetime.utcnow().isoformat(),
            payloads=payloads,
        )
    except Exception as e:
        # Rollback: remove document row and file
        crud.delete_document(int(doc.id))  # type: ignore[arg-type]
        dest_path.unlink(missing_ok=True)
        logger.error("Qdrant upsert failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store embeddings: {e}",
        )

    return schemas.DocumentUploadResponse(
        document=schemas.DocumentRead.model_validate(doc),
        message=f"Successfully uploaded and indexed {len(payloads)} chunks",
    )


@app.get("/admin/documents", response_model=list[schemas.DocumentRead])
def list_documents(
    current_user: models.User = Depends(auth.get_current_admin),
):
    """List all uploaded documents (admin only)."""
    return crud.list_documents()


@app.get("/admin/documents/{doc_id}", response_model=schemas.DocumentRead)
def get_document(
    doc_id: int,
    current_user: models.User = Depends(auth.get_current_admin),
):
    """Get a single document by ID (admin only)."""
    doc = crud.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@app.delete("/admin/documents/{doc_id}", status_code=204)
def delete_document(
    doc_id: int,
    current_user: models.User = Depends(auth.get_current_admin),
):
    """Delete a document, its Qdrant vectors, and the PDF file from disk."""
    doc = crud.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 1. Delete vectors from Qdrant
    try:
        qdrant_service.delete_by_file_id(int(doc.id))  # type: ignore[arg-type]
    except Exception as e:
        logger.error("Qdrant deletion failed for doc %d: %s", doc_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove vectors: {e}",
        )

    # 2. Delete file from disk
    file_path = UPLOADS_DIR / doc.filename
    file_path.unlink(missing_ok=True)

    # 3. Delete DB record
    crud.delete_document(doc_id)
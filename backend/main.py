from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from agentic_chatbot.agent import invoke_memory_agent, generate_chat_title

from . import models, crud, schemas, auth, qdrant_service

import os
import uuid
import logging
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

# Environment variables for URLs
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

# Uploads directory for admin-uploaded PDFs
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# Enhanced FastAPI app with comprehensive documentation
app = FastAPI(
    title="IITD Agent Backend API",
    description="""
    A comprehensive backend API for the IITD Chat Agent system.
    
    ## Features
    
    * **Authentication**: OAuth integration with DevClub (oauth.devclub.in)
    * **Chat Management**: Create, manage, and interact with chat sessions
    * **Document Management**: Upload, process, and manage PDF documents (Admin only)
    * **AI Agent Integration**: Interact with memory-enabled AI agents
    
    ## Authentication Flow
    
    This API uses DevClub OAuth for authentication:
    
    1. **Get Signin URL**: Use `/auth/signin-url` to get the OAuth URL
    2. **Redirect User**: Send user to the OAuth URL for authentication  
    3. **Handle Callback**: Process the OAuth callback with `/auth/callback`
    4. **Use Token**: Include the JWT token in subsequent API calls
    
    ### Frontend Integration
    ```javascript
    // Step 1: Get signin URL
    const response = await fetch('/auth/signin-url?redirect_uri=' + window.location.origin + '/callback');
    const { signin_url } = await response.json();
    
    // Step 2: Redirect user
    window.location.href = signin_url;
    
    // Step 3: Handle callback (in your callback route)
    const { code, state } = urlParams;
    const authResponse = await fetch('/auth/callback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, state })
    });
    const { access_token } = await authResponse.json();
    ```
    
    Most endpoints require authentication using Bearer tokens obtained through the OAuth flow.
    Admin endpoints require elevated privileges.
    
    ## Chat Flow
    
    1. Authenticate using the OAuth flow above
    2. Create a new chat with `/chats/new` (includes first message)
    3. Continue conversation with `/chats/{chat_id}/messages`
    4. Retrieve chat history with `/chats/{chat_id}/messages`
    
    ## Document Management (Admin)
    
    Admins can upload PDF documents that are automatically processed, chunked, and indexed for AI retrieval.
    """,
    version="1.0.0",
    terms_of_service="https://example.com/terms/",
    contact={
        "name": "IITD Agent Team",
        "email": "contact@example.com",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    servers=[
        {"url": BACKEND_URL, "description": "Development server"},
        {"url": "https://api.example.com", "description": "Production server"},
    ],
    swagger_ui_parameters={
        "defaultModelsExpandDepth": 1,
        "defaultModelExpandDepth": 1,
        "displayOperationId": False,
        "displayRequestDuration": True,
        "docExpansion": "list",
        "filter": True,
        "showExtensions": True,
        "showCommonExtensions": True,
        "tryItOutEnabled": True,
    }
)

# Allowed origins for CORS
ALLOWED_ORIGINS = [
    FRONTEND_URL,
    FRONTEND_URL.replace("http://", "http://127.0.0.1:").replace("localhost:", ""),  # 127.0.0.1 variant
    "https://oauth.devclub.in",   # DevClub OAuth server
]

# CORS middleware - allows cross-origin requests from frontend and OAuth provider
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Global exception handler to ensure CORS headers are included in error responses
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions and ensure CORS headers are present."""
    origin = request.headers.get("origin", "")
    
    # Log the error for debugging
    logger.error(f"Unhandled exception: {exc}")
    logger.error(traceback.format_exc())
    
    # Build the error response
    if isinstance(exc, HTTPException):
        status_code = exc.status_code
        detail = exc.detail
    else:
        status_code = 500
        detail = "Internal server error"
    
    response = JSONResponse(
        status_code=status_code,
        content={"detail": detail}
    )
    
    # Add CORS headers if origin is allowed
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    
    return response


# Custom OpenAPI schema with security definitions
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT token obtained from /auth/callback endpoint"
        }
    }
    
    # Add global security requirement for protected endpoints
    for path_data in openapi_schema["paths"].values():
        for operation in path_data.values():
            if isinstance(operation, dict) and "tags" in operation:
                # Skip health endpoint and auth endpoints
                if not any(tag in ["System", "Authentication"] for tag in operation["tags"]):
                    operation["security"] = [{"BearerAuth": []}]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Custom documentation endpoint with enhanced features
@app.get("/docs-advanced", include_in_schema=False)
async def get_advanced_docs():
    """
    Enhanced Swagger UI with additional features for API testing.
    """
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Enhanced API Documentation",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.10.5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.10.5/swagger-ui.css",
        swagger_ui_parameters={
            "defaultModelsExpandDepth": 2,
            "defaultModelExpandDepth": 2,
            "displayOperationId": True,
            "displayRequestDuration": True,
            "docExpansion": "list",
            "filter": True,
            "showExtensions": True,
            "showCommonExtensions": True,
            "tryItOutEnabled": True,
            "persistAuthorization": True,
            "deepLinking": True,
            "supportedSubmitMethods": ["get", "post", "put", "delete", "patch"],
            "validatorUrl": None,  # Disable validation for faster loading
        }
    )

# HTTP bearer handled in auth.get_current_user


@app.on_event("startup")
def on_startup():
    models.init_db()
    print("\n" + "="*60)
    print("🚀 IITD Agent Backend API Server Started")
    print("="*60)
    print("📖 API Documentation Available:")
    print(f"   • Swagger UI:          {BACKEND_URL}/docs")
    print(f"   • Enhanced Swagger:    {BACKEND_URL}/docs-advanced")
    print(f"   • ReDoc:              {BACKEND_URL}/redoc")
    print(f"   • OpenAPI Schema:     {BACKEND_URL}/openapi.json")
    print("\n💡 Tip: Use the 'Enhanced Swagger' for the best testing experience!")
    print("="*60 + "\n")


@app.get("/health", tags=["System"])
def health():
    """
    Health check endpoint to verify the API is running.
    
    Returns a simple status message indicating the service is operational.
    """
    return {"status": "ok"}


@app.get("/auth/signin-url", response_model=schemas.OAuthSigninUrlResponse, tags=["Authentication"])
def get_signin_url(redirect_uri: str):
    """
    Get the DevClub OAuth signin URL.
    
    This endpoint generates the complete OAuth signin URL that your frontend
    should redirect users to for authentication.
    
    - **redirect_uri**: The URL to redirect to after authentication (must be registered with DevClub)
    
    Returns:
        OAuth signin URL for DevClub authentication
        
    Example:
        GET /auth/signin-url?redirect_uri={FRONTEND_URL}/callback
    """
    try:
        signin_url = auth.get_oauth_signin_url(redirect_uri)
        return schemas.OAuthSigninUrlResponse(
            signin_url=signin_url,
            instructions="Redirect user to this URL to initiate OAuth flow"
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/auth/callback", response_model=schemas.TokenResponse, tags=["Authentication"],
          responses={
              200: {"description": "Authentication successful", "model": schemas.TokenResponse},
              400: {"description": "Invalid request parameters"},
              401: {"description": "Authentication failed"},
          })
async def auth_callback(payload: schemas.OAuthCallbackRequest):
    """
    OAuth callback endpoint for DevClub authentication.
    
    This endpoint handles the OAuth callback after successful authentication
    with DevClub and returns a JWT access token.
    
    - **code**: Authorization code from OAuth provider
    - **state**: State parameter for CSRF protection
    
    Returns:
        JWT access token and token type for subsequent API calls
    """
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


@app.post("/chats", response_model=schemas.ChatRead, tags=["Chat Management"])
def create_chat(
    request: schemas.ChatCreate, 
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Create a new chat session.
    
    Creates an empty chat session with an optional title.
    Use `/chats/new` to create a chat with the first message.
    
    - **title**: Optional title for the chat session
    
    Returns:
        Created chat object with ID and metadata
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    chat = crud.create_chat(user_id, request.title)
    return chat


@app.get("/chats", response_model=list[schemas.ChatRead], tags=["Chat Management"])
def list_chats(current_user: models.User = Depends(auth.get_current_user)):
    """
    List all chat sessions for the authenticated user.
    
    Returns all chat sessions owned by the current user,
    ordered by creation date (most recent first).
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    return crud.list_chats(user_id)


@app.get("/chats/{chat_id}", response_model=schemas.ChatRead, tags=["Chat Management"])
def get_chat(chat_id: int, current_user: models.User = Depends(auth.get_current_user)):
    """
    Get details of a specific chat session.
    
    Retrieves metadata for a specific chat session.
    Users can only access their own chats.
    
    - **chat_id**: Unique identifier of the chat session
    """
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@app.post("/chats/new", response_model=schemas.NewChatResponse, tags=["Chat Management"],
          responses={
              200: {"description": "Chat created successfully with AI response"},
              401: {"description": "Authentication required"},
              500: {"description": "Internal server error"},
              502: {"description": "AI agent failed to respond"},
          })
def create_new_chat_with_message(
    message: schemas.MessageCreate, 
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Create a new chat session and send the first message.
    
    This endpoint creates a new chat, sends the first message,
    and returns the AI agent's response along with the chat details.
    
    - **content**: The first message content to send to the AI agent
    
    Returns:
        - chat: The created chat session
        - message: The AI agent's response message  
        - title: Generated or default title for the chat
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    
    # Generate chat title from the first message using LLM
    title_text = generate_chat_title(message.content)
    
    # Create the chat with the title
    chat = crud.create_chat(user_id, title_text)
    
    if chat.id is None:
        raise HTTPException(status_code=500, detail="Failed to create chat")
    
    # Store user message
    crud.create_message(chat_id=chat.id, sender="user", content=message.content)
    
    # Build user context from current user for system prompt
    user_context = {
        "name": current_user.name,
        "email": current_user.email,
        "kerberos": current_user.kerberos,
        "hostel": current_user.hostel,
    }
    
    # Build input dict as expected by agent
    agent_input = {"input": message.content}
    # pass session id as chat id to persist history
    try:
        response = invoke_memory_agent(agent_input, session_id=str(chat.id), user_context=user_context)
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



@app.post("/chats/{chat_id}/messages", response_model=schemas.MessageRead, tags=["Messages"])
def send_message(
    chat_id: int, 
    message: schemas.MessageCreate, 
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Send a message to an existing chat session.
    
    Sends a user message to the AI agent and returns the agent's response.
    The conversation history is maintained within the chat session.
    
    - **chat_id**: ID of the chat session to send the message to
    - **content**: Message content to send to the AI agent
    
    Returns:
        The AI agent's response message
    """
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")

    # store user message
    crud.create_message(chat_id=chat_id, sender="user", content=message.content)

    # Build user context from current user for system prompt
    user_context = {
        "name": current_user.name,
        "email": current_user.email,
        "kerberos": current_user.kerberos,
        "hostel": current_user.hostel,
    }

    # Build input dict as expected by agent
    agent_input = {"input": message.content}
    # pass session id as chat id to persist history
    try:
        response = invoke_memory_agent(agent_input, session_id=str(chat_id), user_context=user_context)
        assistant_text = response.get('output') if isinstance(response, dict) else str(response)
        if assistant_text is None:
            assistant_text = ""
    except Exception as e:
        # Log the exception (print for now). In production, integrate structured logging.
        print("Agent invocation failed:", e)
        raise HTTPException(status_code=502, detail="Agent failed to respond")

    assistant_msg = crud.create_message(chat_id=chat_id, sender="assistant", content=assistant_text)
    return assistant_msg


@app.get("/chats/{chat_id}/messages", response_model=list[schemas.MessageRead], tags=["Messages"])
def get_messages(chat_id: int, current_user: models.User = Depends(auth.get_current_user)):
    """
    Get all messages from a chat session.
    
    Retrieves the complete conversation history for a specific chat session.
    Messages are returned in chronological order.
    
    - **chat_id**: ID of the chat session to retrieve messages from
    
    Returns:
        List of all messages in the chat session (user and assistant)
    """
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return crud.list_messages(chat_id)

@app.delete("/chats/{chat_id}", status_code=204, tags=["Chat Management"])
def delete_chat_endpoint(chat_id: int, current_user: models.User = Depends(auth.get_current_user)):
    """
    Delete a chat session and all its messages.
    
    Permanently removes a chat session and all associated messages.
    This action cannot be undone.
    
    - **chat_id**: ID of the chat session to delete
    """
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    crud.delete_chat(chat_id)
    return {"detail": "Chat deleted"}


# ============================================================
# Admin – Document Management Routes
# ============================================================


@app.post("/admin/documents", response_model=schemas.DocumentUploadResponse, tags=["Admin - Document Management"],
          responses={
              200: {"description": "Document uploaded and processed successfully"},
              400: {"description": "Invalid file type or request"},
              401: {"description": "Authentication required"},
              403: {"description": "Admin privileges required"},
              500: {"description": "Processing failed - check file format and try again"},
          })
async def upload_document(
    file: UploadFile = File(..., description="PDF file to upload and process"),
    description: str = Form("", description="Optional description for the document"),
    current_user: models.User = Depends(auth.get_current_admin),
):
    """
    Upload and process a PDF document (Admin only).
    
    This endpoint allows admins to upload PDF documents that are:
    1. Validated for file type (PDF only)
    2. Chunked into semantic sections
    3. Embedded using AI models
    4. Stored in Qdrant vector database for retrieval
    
    **Requirements:**
    - Must be authenticated as an admin user
    - File must be in PDF format
    - File size limits may apply
    
    **Process:**
    1. File validation and storage
    2. PDF chunking and text extraction
    3. Embedding generation
    4. Vector database storage
    
    - **file**: PDF file (application/pdf only)
    - **description**: Optional description to help categorize the document
    
    Returns:
        Document metadata and processing confirmation
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


@app.get("/admin/documents", response_model=list[schemas.DocumentRead], tags=["Admin - Document Management"])
def list_documents(
    current_user: models.User = Depends(auth.get_current_admin),
):
    """
    List all uploaded documents (Admin only).
    
    Returns a list of all documents that have been uploaded and processed,
    including metadata such as file size, chunk count, and upload date.
    
    **Admin access required.**
    """
    return crud.list_documents()


@app.get("/admin/documents/{doc_id}", response_model=schemas.DocumentRead, tags=["Admin - Document Management"])
def get_document(
    doc_id: int,
    current_user: models.User = Depends(auth.get_current_admin),
):
    """
    Get details of a specific document (Admin only).
    
    Retrieves comprehensive metadata for a specific document,
    including processing statistics and upload information.
    
    - **doc_id**: Unique identifier of the document
    
    **Admin access required.**
    """
    doc = crud.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@app.delete("/admin/documents/{doc_id}", status_code=204, tags=["Admin - Document Management"])
def delete_document(
    doc_id: int,
    current_user: models.User = Depends(auth.get_current_admin),
):
    """
    Delete a document and all associated data (Admin only).
    
    This endpoint performs a complete removal of a document:
    1. Removes vector embeddings from Qdrant database
    2. Deletes the physical PDF file from storage
    3. Removes the document record from the database
    
    **This action is irreversible.**
    
    - **doc_id**: Unique identifier of the document to delete
    
    **Admin access required.**
    """
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
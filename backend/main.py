from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, StreamingResponse
from agentic_chatbot.agent import invoke_memory_agent, generate_chat_title, stream_memory_agent

from . import models, crud, schemas, auth, qdrant_service

import os
import uuid
import logging
import traceback
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# Programme code mapping from kerberos prefix to programme name
PROGRAMME_CODES = {
    # B.Tech.
    "am1": "B.Tech. in Engineering and Computational Mechanics",
    "bb1": "B.Tech. in Biochemical Engineering and Biotechnology",
    "ch1": "B.Tech. in Chemical Engineering",
    "cs1": "B.Tech. in Computer Science and Engineering",
    "ce1": "B.Tech. in Civil Engineering",
    "ee1": "B.Tech. in Electrical Engineering",
    "ee3": "B.Tech. in Electrical Engineering (Power and Automation)",
    "es1": "B.Tech. in Energy Engineering",
    "ms1": "B.Tech. in Materials Engineering",
    "mt1": "B.Tech. in Mathematics & Computing",
    "me1": "B.Tech. in Mechanical Engineering",
    "me2": "B.Tech. in Production and Industrial Engineering",
    "ph1": "B.Tech. in Engineering Physics",
    "tt1": "B.Tech. in Textile Technology",
    # Dual Degree
    "ch7": "B.Tech. and M.Tech. in Chemical Engineering",
    "cs5": "B.Tech. and M.Tech. in Computer Science and Engineering",
    "mt6": "B.Tech. and M.Tech. in Mathematics & Computing",
    # M.Tech.
    "ama": "M.Tech. in Engineering Analysis and Design",
    "bem": "M.Tech. in Biomolecular and Bioprocess Engineering",
    "che": "M.Tech. in Chemical Engineering",
    "cym": "M.Tech. in Molecular Engg.: Chemical Synthesis & Analysis",
    "ceg": "M.Tech. in Geotechnical and Geoenvironmental Engineering",
    "ceu": "M.Tech. in Rock Engineering and Underground Structures",
    "ces": "M.Tech. in Structural Engineering",
    "cew": "M.Tech. in Water Resources Engineering",
    "cet": "M.Tech. in Construction Engineering and Management",
    "cec": "M.Tech. in Construction Technology and Management",
    "cev": "M.Tech. in Environmental Engineering and Management",
    "cep": "M.Tech. in Transportation Engineering",
    "mcs": "M.Tech. in Computer Science and Engineering",
    "eee": "M.Tech. in Communications Engineering",
    "eet": "M.Tech. in Computer Technology",
    "eea": "M.Tech. in Control and Automation",
    "een": "M.Tech. in Integrated Electronics and Circuits",
    "eep": "M.Tech. in Power Electronics, Electrical Machines and Drives",
    "ees": "M.Tech. in Power Systems",
    "esn": "M.Tech. in Energy & Environment Technologies and Management",
    "esr": "M.Tech. in Renewable Energy Technologies and Management",
    "msm": "M.Tech. in Materials Engineering",
    "msp": "M.Tech. in Polymer Science and Technology",
    "mem": "M.Tech. in Mechanical Design",
    "mee": "M.Tech. in Industrial Engineering",
    "mep": "M.Tech. in Production Engineering",
    "met": "M.Tech. in Thermal Engineering",
    "pha": "M.Tech. in Applied Optics",
    "phm": "M.Tech. in Solid State Materials",
    "ttf": "M.Tech. in Fibre Science & Technology",
    "tte": "M.Tech. in Textile Engineering",
    "ttc": "M.Tech. in Textile Chemical Processing",
    "crf": "M.Tech. in Radio Frequency Design and Technology",
    "ast": "M.Tech. in Atmospheric-Oceanic Science and Technology",
    "cte": "M.Tech. in Electric Mobility",
    "bmt": "M.Tech. in Biomedical Engineering",
    "aib": "M.Tech. in Machine Intelligence and Data Science",
    "jcs": "M.Tech. in Cyber Security",
    "jes": "M.Tech. in Energy Studies",
    "jit": "M.Tech. in Industrial Tribology and Maintenance Engineering",
    "jid": "M.Tech. in Instrument Technology",
    "jop": "M.Tech. in Optoelectronics and Optical Communication",
    "jtm": "M.Tech. in Telecommunication Technology Management",
    "jrb": "M.Tech. in Robotics",
    "jvl": "M.Tech. in VLSI Design Tools and Technology",
    # M.S.(R)
    "siy": "M.S.(R) in Information Technology",
    "amy": "M.S.(R) in Applied Mechanics",
    "asy": "M.S.(R) in Atmospheric and Oceanic Sciences",
    "cty": "M.S.(R) in Automotive Research and Tribology",
    "bsy": "M.S.(R) in Telecommunication Technology and Management",
    "bey": "M.S.(R) in Biochemical Engg. and Biotechnology",
    "chy": "M.S.(R) in Chemical Engineering",
    "cey": "M.S.(R) in Civil Engineering",
    "csy": "M.S.(R) in Computer Science and Engineering",
    "eey": "M.S.(R) in Electrical Engineering",
    "esy": "M.S.(R) in Energy Science and Engineering",
    "msy": "M.S.(R) in Materials Science and Engineering",
    "mey": "M.S.(R) in Mechanical Engineering",
    "bly": "M.S.(R) in Biological Sciences",
    "jvy": "M.S.(R) in VLSI Design Tools and Technology",
    "idy": "M.S.(R) in Sensors, Instrumentation and Cyber-Physical Systems Engineering",
    "try": "M.S.(R) in Transportation Safety and Injury Prevention",
    "aiy": "M.S.(R) in Machine Intelligence and Data Science",
    # M.Des.
    "dds": "Master of Design in Industrial Design",
    # MBA
    "smg": "M.B.A.",
    "smt": "M.B.A. (with focus on Telecommunication Systems Management)",
    "smn": "Executive M.B.A. Programme",
    # M.Sc.
    "cys": "M.Sc. in Chemistry",
    "hcs": "M.Sc. in Cognitive Science",
    "hes": "M.Sc. in Economics",
    "mas": "M.Sc. in Mathematics",
    "phs": "M.Sc. in Physics",
    "bls": "M.Sc. in Biological Sciences",
    # M.P.P.
    "ppm": "Master of Public Policy",
    # M.A.
    "hst": "M.A. in Culture, Society, and Thought",
    # P.G. Diploma
    "amx": "P.G. D.I.I.T (Naval Construction)",
    "mvx": "Joint P.G. Diploma in Visionary Leadership in Manufacturing",
}


def parse_kerberos(kerberos: str | None) -> dict:
    """
    Parse kerberos ID to extract programme code and year of joining.
    
    Kerberos format: [3-letter programme code][2-digit year][5-digit roll number]
    Example: me2241111 -> programme_code=ME2, year_of_joining=2024
    
    Returns dict with programme_code, programme_name, and year_of_joining (or None if invalid)
    """
    if not kerberos or len(kerberos) < 5:
        return {"programme_code": None, "programme_name": None, "year_of_joining": None}
    
    programme_code = kerberos[:3].upper()
    year_digits = kerberos[3:5]
    
    # Parse year (assume 20xx for now)
    try:
        year_of_joining = 2000 + int(year_digits)
    except ValueError:
        year_of_joining = None
    
    # Look up programme name
    programme_name = PROGRAMME_CODES.get(kerberos[:3].lower())
    
    return {
        "programme_code": programme_code,
        "programme_name": programme_name,
        "year_of_joining": year_of_joining,
    }


def build_user_context(user: models.User) -> dict:
    """Build user context dict from user model, including parsed kerberos info."""
    kerberos_info = parse_kerberos(user.kerberos)
    
    return {
        "name": user.name,
        "email": user.email,
        "kerberos": user.kerberos,
        "hostel": user.hostel,
        "programme_code": kerberos_info["programme_code"],
        "programme_name": kerberos_info["programme_name"],
        "year_of_joining": kerberos_info["year_of_joining"],
    }


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
    
    * **Authentication**: OAuth integration with IITD OAuth (auth.devclub.in)
    * **Chat Management**: Create, manage, and interact with chat sessions
    * **Document Management**: Upload, process, and manage PDF documents (Admin only)
    * **AI Agent Integration**: Interact with memory-enabled AI agents
    
    ## Authentication Flow
    
    This API uses IITD OAuth for authentication:
    
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
    "https://auth.devclub.in",   # IITD OAuth server
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
    Get the IITD OAuth signin URL with PKCE.
    
    This endpoint generates the complete OAuth authorization URL that your frontend
    should redirect users to for authentication. Uses PKCE (S256) for security.
    
    - **redirect_uri**: The URL to redirect to after authentication (must be registered)
    
    Returns:
        OAuth signin URL and state parameter
        
    Example:
        GET /auth/signin-url?redirect_uri={FRONTEND_URL}/callback
    """
    try:
        state, signin_url = auth.create_oauth_state(redirect_uri)
        return schemas.OAuthSigninUrlResponse(
            signin_url=signin_url,
            state=state,
            instructions="Redirect user to this URL to initiate OAuth flow. The state is stored server-side with PKCE parameters."
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
    OAuth callback endpoint for IITD authentication.
    
    This endpoint handles the OAuth callback after successful authentication
    with IITD OAuth and returns an access token.
    
    - **code**: Authorization code from OAuth provider
    - **state**: State parameter for CSRF protection and PKCE lookup
    
    Returns:
        Access token and token type for subsequent API calls
    """
    code = payload.code
    state = payload.state

    # Validate incoming parameters
    print("Auth callback received code:", code[:20] + "...", "state:", state)
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state in the request"
        )
    
    # Exchange authorization code for access token (with PKCE verification)
    access_token, user_info = await auth.exchange_code_for_token(code, state)
    
    # Get or create user in database
    user = crud.get_or_create_user(user_info)
    print("Authenticated user:", user.email, "oauth_id:", user.oauth_id)
    
    return {"access_token": access_token, "token_type": "bearer"}
    
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
    user_context = build_user_context(current_user)
    
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
    user_context = build_user_context(current_user)

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


@app.post("/chats/{chat_id}/messages/stream", tags=["Messages"])
async def send_message_stream(
    chat_id: int, 
    message: schemas.MessageCreate, 
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Send a message to an existing chat session with streaming response.
    
    Sends a user message to the AI agent and streams the agent's response
    using Server-Sent Events (SSE). The conversation history is maintained.
    
    - **chat_id**: ID of the chat session to send the message to
    - **content**: Message content to send to the AI agent
    
    Returns:
        SSE stream of the agent's response tokens
    """
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")

    # store user message
    crud.create_message(chat_id=chat_id, sender="user", content=message.content)

    # Build user context from current user for system prompt
    user_context = build_user_context(current_user)

    # Build input dict as expected by agent
    agent_input = {"input": message.content}
    
    async def generate_stream():
        """Generate SSE stream of agent response tokens."""
        full_response = ""
        try:
            async for token in stream_memory_agent(agent_input, session_id=str(chat_id), user_context=user_context):
                full_response += token
                # Send each token as an SSE event
                yield f"data: {json.dumps({'token': token})}\n\n"
            
            # Store the complete assistant message after streaming finishes
            assistant_msg = crud.create_message(chat_id=chat_id, sender="assistant", content=full_response)
            
            # Send completion event with message metadata
            yield f"data: {json.dumps({'done': True, 'message_id': str(assistant_msg.id)})}\n\n"
        except Exception as e:
            print("Agent streaming failed:", e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@app.post("/chats/new/stream", tags=["Chat Management"])
async def create_new_chat_with_message_stream(
    message: schemas.MessageCreate, 
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Create a new chat session and send the first message with streaming response.
    
    This endpoint creates a new chat, sends the first message,
    and streams the AI agent's response using Server-Sent Events (SSE).
    
    - **content**: The first message content to send to the AI agent
    
    Returns:
        SSE stream starting with chat metadata, then response tokens
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
    user_context = build_user_context(current_user)
    
    # Build input dict as expected by agent
    agent_input = {"input": message.content}
    
    async def generate_stream():
        """Generate SSE stream starting with chat info, then agent response tokens."""
        # First, send the chat metadata
        yield f"data: {json.dumps({'chat': {'id': str(chat.id), 'title': title_text}})}\n\n"
        
        full_response = ""
        try:
            async for token in stream_memory_agent(agent_input, session_id=str(chat.id), user_context=user_context):
                full_response += token
                # Send each token as an SSE event
                yield f"data: {json.dumps({'token': token})}\n\n"
            
            # Store the complete assistant message after streaming finishes
            assistant_msg = crud.create_message(chat_id=chat.id, sender="assistant", content=full_response)
            
            # Send completion event with message metadata
            yield f"data: {json.dumps({'done': True, 'message_id': str(assistant_msg.id)})}\n\n"
        except Exception as e:
            print("Agent streaming failed:", e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


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
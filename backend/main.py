import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the backend root directory (one level up from this package)
# override=True so --reload picks up .env edits (e.g. RATE_LIMIT_GUEST_TOKENS)
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, StreamingResponse

from . import models, crud, schemas, auth, qdrant_service
from .logging_config import setup_logging, get_logger

import uuid
import traceback
import json
import asyncio
import base64
import hashlib
import secrets
import time

# Set up logging before anything else
setup_logging()
logger = get_logger(__name__)

# Import agent functions after logging is configured
from agentic_chatbot.agent import (
    invoke_memory_agent,
    generate_chat_title,
    stream_memory_agent,
    stream_memory_agent_with_status,
    stream_memory_agent_data_stream,
    message_history_to_thread_messages,
    classify_openrouter_error,
)
from agentic_chatbot import data_stream as ds

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


def build_user_context(user: models.User | None) -> dict:
    """Build user context dict from user model, including parsed kerberos info and courses done.
    
    If user is None (guest mode), returns a dict with all fields set to None.
    """
    from backend.curriculum.generation import generation_from_entry_year

    if user is None:
        return {
            "name": None,
            "email": None,
            "kerberos": None,
            "hostel": None,
            "entry_number": None,
            "department": None,
            "category": None,
            "programme_code": None,
            "programme_name": None,
            "year_of_joining": None,
            "curriculum_generation": None,
            "courses_done": {},
        }
    
    kerberos_info = parse_kerberos(user.kerberos)
    
    # Get user's courses
    courses_done = {}
    if user.id:
        courses_by_semester = crud.get_user_courses(int(user.id))
        # Convert to string keys for JSON compatibility
        courses_done = {str(k): v for k, v in courses_by_semester.items()}
    
    year = kerberos_info["year_of_joining"]
    context = {
        "name": user.name,
        "email": user.email,
        "kerberos": user.kerberos,
        "hostel": user.hostel,
        "entry_number": user.entry_number,
        "department": user.department,
        "category": user.category,
        "programme_code": kerberos_info["programme_code"],
        "programme_name": kerberos_info["programme_name"],
        "year_of_joining": year,
        "curriculum_generation": generation_from_entry_year(year),
        "courses_done": courses_done,
    }
    
    logger.debug(f"Built user context for {user.email}: programme={kerberos_info['programme_code']}")
    return context


# Environment variables for URLs
# FRONTEND_URL may be a single origin or comma-separated list (Vite :5173 + Docker :3000)
_FRONTEND_URL_RAW = os.environ.get("FRONTEND_URL", "http://localhost:5173")
FRONTEND_ORIGINS = [o.strip() for o in _FRONTEND_URL_RAW.split(",") if o.strip()]
FRONTEND_URL = FRONTEND_ORIGINS[0] if FRONTEND_ORIGINS else "http://localhost:5173"
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
# Public path prefix when behind nginx (e.g. /backend → strips to app routes)
ROOT_PATH = os.environ.get("ROOT_PATH", "").rstrip("/")

_OPENROUTER_PKCE: dict[int, tuple[str, float]] = {}
_OPENROUTER_PKCE_TTL_SECONDS = 600


def _pkce_token(length: int = 48) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(length)).decode("ascii").rstrip("=")


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _openrouter_callback_url() -> str:
    return f"{FRONTEND_URL.rstrip('/')}/openrouter/callback"

# Uploads directory for admin-uploaded PDFs
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# Enhanced FastAPI app with comprehensive documentation
app = FastAPI(
    title="IITD Agent Backend API",
    root_path=ROOT_PATH,
    description="""
    A comprehensive backend API for the IITD Chat Agent system.
    
    ## Features
    
    * **Authentication**: OIDC via DevClub (https://auth.devclub.in) — PKCE S256
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
ALLOWED_ORIGINS = []
for origin in FRONTEND_ORIGINS:
    ALLOWED_ORIGINS.append(origin)
    # Also allow the 127.0.0.1 variant of localhost origins
    if "localhost" in origin:
        ALLOWED_ORIGINS.append(origin.replace("localhost", "127.0.0.1"))
ALLOWED_ORIGINS.append("https://auth.devclub.in")  # IITD OAuth server
ALLOWED_ORIGINS = list(dict.fromkeys(ALLOWED_ORIGINS))

# CORS middleware - allows cross-origin requests from frontend and OAuth provider
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

from .admin_portal import router as portal_router

app.include_router(portal_router)


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
        openapi_url=f"{ROOT_PATH}{app.openapi_url}",
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
    try:
        from .quota import ensure_usage_tables
        ensure_usage_tables()
    except Exception as e:
        logger.warning(f"Could not ensure llm_usage tables: {e}")
    logger.info("=" * 60)
    logger.info("IITD Agent Backend API Server Started")
    logger.info("=" * 60)
    logger.info(f"Swagger UI: {BACKEND_URL}/docs")
    logger.info(f"ReDoc: {BACKEND_URL}/redoc")
    # Log auth configuration status
    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")
    logger.info(f"CLIENT_ID configured: {bool(client_id)} ({'set' if client_id else 'MISSING - auth will fail'})")
    logger.info(f"CLIENT_SECRET configured: {bool(client_secret)} ({'set' if client_secret else 'MISSING - auth will fail'})")
    logger.info(f"DEMO_MODE: {os.environ.get('DEMO_MODE', 'false')}")
    logger.info(f"RATE_LIMIT_ENABLED: {os.environ.get('RATE_LIMIT_ENABLED', 'true')}")
    logger.info("=" * 60)


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
    logger.info(f"[get_signin_url] Request received with redirect_uri={redirect_uri}")
    try:
        state, signin_url = auth.create_oauth_state(redirect_uri)
        logger.info(f"[get_signin_url] Returning signin_url for state={state}")
        return schemas.OAuthSigninUrlResponse(
            signin_url=signin_url,
            state=state,
            instructions="Redirect user to this URL to initiate OAuth flow. The state is stored server-side with PKCE parameters."
        )
    except ValueError as e:
        logger.error(f"[get_signin_url] Failed: {e}")
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
    logger.info(f"Auth callback received for state: {state}")
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state in the request"
        )
    
    # Exchange authorization code with DevClub OIDC (PKCE + client_secret_post)
    _idp_access_token, user_info = await auth.exchange_code_for_token(code, state)

    # Get or create user in database
    user = crud.get_or_create_user(user_info)
    logger.info(f"Authenticated user: {user.email}")

    # Mint our own API JWT (frontend keeps receiving { access_token, token_type })
    subject = user.oauth_id or str(user.id)
    access_token = auth.create_access_token({"sub": subject})

    return {"access_token": access_token, "token_type": "bearer"}


# ---------- User Profile & Courses Endpoints ----------

# Path to programme structures
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROGRAMME_DIR = _BACKEND_DIR / "sources" / "programme_structures"


def get_programme_structure(programme_code: str) -> dict | None:
    """Load programme structure JSON for a given programme code."""
    programme_file = _PROGRAMME_DIR / f'{programme_code.upper()}.json'
    try:
        with open(programme_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def get_max_semesters(programme_code: str | None) -> int:
    """Get maximum semesters for a programme (8 for B.Tech, 10 for Dual/M.Tech)."""
    if not programme_code:
        return 8
    
    programme = get_programme_structure(programme_code)
    if programme and programme.get("dual"):
        return 10
    
    # Check if M.Tech or Dual based on code patterns
    code_lower = programme_code.lower()
    if any(code_lower.startswith(p) for p in ["ch7", "cs5", "mt6"]):  # Dual degrees
        return 10
    if len(code_lower) == 3 and code_lower[2].isalpha():  # M.Tech patterns like "che", "mcs"
        return 4  # M.Tech is typically 4 semesters
    
    return 8  # Default for B.Tech


def calculate_current_semester(year_of_joining: int | None) -> int:
    """Calculate estimated current semester based on year of joining."""
    if not year_of_joining:
        return 1
    
    from datetime import datetime
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    # Academic year starts in August
    academic_years_completed = current_year - year_of_joining
    if current_month >= 8:  # After August, new academic year
        academic_years_completed += 1
    
    # Each academic year has 2 semesters
    current_semester = academic_years_completed * 2
    if current_month >= 1 and current_month < 8:
        # Spring semester (Jan-May) is the even semester
        pass  # Already correct
    else:
        # Fall semester (Aug-Dec) is the odd semester
        current_semester -= 1
    
    return max(1, min(current_semester, 10))


@app.get("/user/profile", response_model=schemas.UserProfileResponse, tags=["User Profile"])
def get_user_profile(current_user: models.User = Depends(auth.get_current_user)):
    """
    Get the current user's profile information.
    
    Returns user data including parsed kerberos info and programme details.
    """
    kerberos_info = parse_kerberos(current_user.kerberos)
    programme_code = kerberos_info.get("programme_code")
    
    return schemas.UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        kerberos=current_user.kerberos,
        entry_number=current_user.entry_number,
        department=current_user.department,
        hostel=current_user.hostel,
        category=current_user.category,
        programme_code=programme_code,
        programme_name=kerberos_info.get("programme_name"),
        year_of_joining=kerberos_info.get("year_of_joining"),
        max_semesters=get_max_semesters(programme_code),
    )


@app.get("/user/courses", response_model=schemas.UserCoursesResponse, tags=["User Profile"])
def get_user_courses(current_user: models.User = Depends(auth.get_current_user)):
    """
    Get the current user's courses grouped by semester.
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    
    courses = crud.get_user_courses(int(current_user.id))
    # Convert int keys to string keys for JSON
    courses_str_keys = {str(k): v for k, v in courses.items()}
    return schemas.UserCoursesResponse(courses=courses_str_keys)


@app.put("/user/courses", response_model=schemas.UserCoursesUpdateResponse, tags=["User Profile"])
def update_user_courses(
    request: schemas.UserCoursesUpdateRequest,
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Update the current user's courses.
    
    Validates each course code against the courses database.
    Invalid courses are reported but not saved.
    """
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    
    user_id = int(current_user.id)
    
    # Validate all courses first
    valid_courses: dict[int, list[str]] = {}
    all_valid: list[str] = []
    all_invalid: list[str] = []
    
    for semester_str, course_codes in request.courses.items():
        try:
            semester = int(semester_str)
        except ValueError:
            continue  # Skip invalid semester keys
        
        valid_courses[semester] = []
        for code in course_codes:
            code = code.upper().strip()
            if not code:
                continue
            if crud.validate_course_code(code):
                valid_courses[semester].append(code)
                all_valid.append(code)
            else:
                all_invalid.append(code)
    
    # Save valid courses
    saved = crud.set_user_courses(user_id, valid_courses)
    saved_str_keys = {str(k): v for k, v in saved.items()}
    
    return schemas.UserCoursesUpdateResponse(
        courses=saved_str_keys,
        validation=schemas.CourseValidationResult(valid=all_valid, invalid=all_invalid)
    )


@app.get("/user/courses/defaults", response_model=schemas.DefaultCoursesResponse, tags=["User Profile"])
def get_default_courses(current_user: models.User = Depends(auth.get_current_user)):
    """
    Get default courses from programme structure for completed semesters.
    
    Returns the recommended courses from the user's programme structure
    for semesters 1 through (current semester - 1).
    """
    kerberos_info = parse_kerberos(current_user.kerberos)
    programme_code = kerberos_info.get("programme_code")
    year_of_joining = kerberos_info.get("year_of_joining")
    
    current_semester = calculate_current_semester(year_of_joining)
    completed_semesters = max(0, current_semester - 1)
    
    courses: dict[str, list[str]] = {}
    programme_name = kerberos_info.get("programme_name")
    
    if programme_code:
        programme = get_programme_structure(programme_code)
        if programme:
            programme_name = programme.get("name", programme_name)
            recommended = programme.get("recommended", [])
            
            # Get courses for completed semesters only
            for i, semester_courses in enumerate(recommended):
                semester_num = i + 1  # 1-indexed
                if semester_num <= completed_semesters:
                    courses[str(semester_num)] = semester_courses
    
    return schemas.DefaultCoursesResponse(
        programme_code=programme_code,
        programme_name=programme_name,
        year_of_joining=year_of_joining,
        current_semester=current_semester,
        courses=courses,
    )


@app.get("/courses/search", response_model=schemas.CourseSearchResponse, tags=["User Profile"])
def search_courses(
    q: str,
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Search courses by code prefix for autocomplete.
    
    - **q**: Course code prefix to search (e.g., "COL", "MT")
    
    Returns up to 20 matching courses.
    """
    if len(q) < 2:
        return schemas.CourseSearchResponse(courses=[])
    
    results = crud.search_courses_by_prefix(q)
    return schemas.CourseSearchResponse(
        courses=[schemas.CourseSearchResult(code=r["code"], name=r["name"]) for r in results]
    )


@app.get("/user/usage", response_model=schemas.UsageStatusResponse, tags=["User Profile"])
def get_user_usage(
    request: Request,
    response: Response,
    current_user: models.User | None = Depends(auth.get_optional_user),
):
    """Rolling token window status (prompt + completion)."""
    from . import llm_clients, quota
    from .device_id import ensure_device_cookie

    device = ensure_device_cookie(request, response)
    user_id = int(current_user.id) if current_user and current_user.id is not None else None
    has_byok = llm_clients.user_has_byok(user_id) if user_id else False
    status = quota.check_quota(
        user_id=user_id,
        device_fingerprint=device.fingerprint,
        has_byok=has_byok,
    )
    return schemas.UsageStatusResponse(
        used=status.used,
        limit=status.limit,
        remaining=status.remaining,
        window_hours=status.window_hours,
        resets_at=status.resets_at.isoformat() if status.resets_at else None,
        byok=status.byok,
        providers=list(llm_clients.PROVIDER_PRESETS.keys()),
    )


@app.get("/user/llm-credentials", tags=["User Profile"])
def get_llm_credentials(current_user: models.User = Depends(auth.get_current_user)):
    from . import llm_clients

    view = llm_clients.credentials_public_view(int(current_user.id))
    if not view:
        return {"connected": False, "credentials": None}
    return {"connected": True, "credentials": view}


@app.put("/user/llm-credentials", tags=["User Profile"])
async def put_llm_credentials(
    body: schemas.LlmCredentialsUpsert,
    current_user: models.User = Depends(auth.get_current_user),
):
    """Store encrypted BYOK credentials. Never returns the raw key."""
    from . import llm_clients

    try:
        await llm_clients.validate_credentials(
            body.provider, body.api_key, body.base_url, body.model
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Credential validation failed: {e}")
    try:
        saved = llm_clients.save_user_credentials(
            int(current_user.id),
            provider=body.provider,
            api_key=body.api_key,
            base_url=body.base_url,
            model=body.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"connected": True, "credentials": saved}


@app.patch("/user/llm-credentials/model", tags=["User Profile"])
def patch_llm_credentials_model(
    body: schemas.LlmCredentialsModelUpdate,
    current_user: models.User = Depends(auth.get_current_user),
):
    """Update the saved LLM model without replacing the encrypted credential."""
    from . import llm_clients

    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    try:
        updated = llm_clients.update_user_credentials_model(
            int(current_user.id),
            body.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="No active LLM credentials found")
    return {"connected": True, "credentials": updated}


@app.patch("/user/llm-credentials/enabled", tags=["User Profile"])
def patch_llm_credentials_enabled(
    body: schemas.LlmCredentialsEnabledUpdate,
    current_user: models.User = Depends(auth.get_current_user),
):
    """Enable or disable saved credentials without deleting them."""
    from . import llm_clients

    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    updated = llm_clients.update_user_credentials_enabled(
        int(current_user.id),
        body.enabled,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="No active LLM credentials found")
    return {"connected": True, "credentials": updated}


@app.delete("/user/llm-credentials", tags=["User Profile"])
def delete_llm_credentials(current_user: models.User = Depends(auth.get_current_user)):
    from . import llm_clients

    deleted = llm_clients.delete_user_credentials(int(current_user.id))
    return {"connected": False, "deleted": deleted}


@app.get(
    "/user/llm-credentials/openrouter/start",
    response_model=schemas.OpenRouterOAuthStartResponse,
    tags=["User Profile"],
)
def start_openrouter_oauth(current_user: models.User = Depends(auth.get_current_user)):
    """Start OpenRouter PKCE OAuth and keep the verifier server-side."""
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    verifier = _pkce_token()
    challenge = _pkce_s256(verifier)
    _OPENROUTER_PKCE[user_id] = (verifier, time.time() + _OPENROUTER_PKCE_TTL_SECONDS)
    callback_url = _openrouter_callback_url()
    params = {
        "callback_url": callback_url,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    from urllib.parse import urlencode

    return {
        "auth_url": f"https://openrouter.ai/auth?{urlencode(params)}"
    }


@app.post("/user/llm-credentials/openrouter/callback", tags=["User Profile"])
async def finish_openrouter_oauth(
    body: schemas.OpenRouterOAuthCallbackRequest,
    current_user: models.User = Depends(auth.get_current_user),
):
    """Exchange OpenRouter OAuth code for a user-owned API key and store it encrypted."""
    from . import llm_clients
    import httpx

    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    verifier_data = _OPENROUTER_PKCE.pop(user_id, None)
    if not verifier_data:
        raise HTTPException(status_code=400, detail="OpenRouter authorization was not started or has expired")
    verifier, expires_at = verifier_data
    if time.time() > expires_at:
        raise HTTPException(status_code=400, detail="OpenRouter authorization code expired. Try connecting again.")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(
                "https://openrouter.ai/api/v1/auth/keys",
                json={
                    "code": body.code,
                    "code_verifier": verifier,
                    "code_challenge_method": "S256",
                },
            )
        res.raise_for_status()
        payload = res.json()
        key = payload.get("key")
        if not key:
            raise ValueError("OpenRouter did not return an API key")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OpenRouter authorization failed: {e}")

    saved = llm_clients.save_user_credentials(
        user_id,
        provider="openrouter",
        api_key=key,
        auth_method="oauth",
    )
    return {"connected": True, "credentials": saved}


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
              500: {"description": "Internal server error"},
              502: {"description": "AI agent failed to respond"},
          })
def create_new_chat_with_message(
    message: schemas.MessageCreate, 
    current_user: models.User | None = Depends(auth.get_optional_user)
):
    """
    Create a new chat session and send the first message.
    
    Authenticated users get a persisted chat; guests get an ephemeral response.
    
    - **content**: The first message content to send to the AI agent
    
    Returns:
        - chat: The created chat session (or ephemeral placeholder for guests)
        - message: The AI agent's response message  
        - title: Generated or default title for the chat
    """
    is_guest = current_user is None
    
    # Generate chat title from the first message using LLM
    title_text = generate_chat_title(message.content)
    
    if is_guest:
        # Guest mode: no DB persistence
        import uuid
        guest_session_id = f"guest-{uuid.uuid4()}"
        user_context = build_user_context(None)
        agent_input = {"input": message.content}
        
        try:
            response = invoke_memory_agent(agent_input, session_id=guest_session_id, user_context=user_context)
            assistant_text = response.get('output') if isinstance(response, dict) else str(response)
            if assistant_text is None:
                assistant_text = ""
        except Exception as e:
            logger.error(f"Agent invocation failed (guest): {e}", exc_info=True)
            raise HTTPException(status_code=502, detail="Agent failed to respond")
        
        # Return ephemeral response (no real IDs)
        return {
            "chat": {"id": guest_session_id, "user_id": None, "title": title_text, "created_at": None},
            "message": {"id": guest_session_id, "chat_id": guest_session_id, "sender": "assistant", "content": assistant_text, "created_at": None},
            "title": title_text
        }
    
    # Authenticated user: persist to DB
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    
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
        logger.error(f"Agent invocation failed: {e}", exc_info=True)
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
        logger.error(f"Agent invocation failed: {e}", exc_info=True)
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
            logger.error(f"Agent streaming failed: {e}", exc_info=True)
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
    current_user: models.User | None = Depends(auth.get_optional_user)
):
    """
    Create a new chat session and send the first message with streaming response.
    
    Authenticated users get a persisted chat; guests get an ephemeral stream.
    
    - **content**: The first message content to send to the AI agent
    
    Returns:
        SSE stream starting with chat metadata, then response tokens
    """
    is_guest = current_user is None
    
    # Generate chat title from the first message using LLM
    title_text = generate_chat_title(message.content)
    
    if is_guest:
        import uuid
        guest_session_id = f"guest-{uuid.uuid4()}"
        user_context = build_user_context(None)
        agent_input = {"input": message.content}
        
        async def generate_guest_stream():
            yield f"data: {json.dumps({'chat': {'id': guest_session_id, 'title': title_text}})}\n\n"
            full_response = ""
            try:
                async for token in stream_memory_agent(
                    agent_input, session_id=guest_session_id, user_context=user_context
                ):
                    full_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield f"data: {json.dumps({'done': True, 'message_id': guest_session_id})}\n\n"
            except Exception as e:
                logger.error(f"Agent streaming failed (guest): {e}", exc_info=True)
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        return StreamingResponse(
            generate_guest_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    
    # Authenticated user: persist to DB
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="Invalid user id")
    user_id = int(current_user.id)
    
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
            logger.error(f"Agent streaming failed: {e}", exc_info=True)
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


@app.patch("/chats/{chat_id}", response_model=schemas.ChatRead, tags=["Chat Management"])
def patch_chat(
    chat_id: int,
    request: schemas.ChatCreate,
    current_user: models.User = Depends(auth.get_current_user),
):
    """Rename a chat (title)."""
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    updated = crud.update_chat_title(chat_id, request.title or "New Chat")
    if not updated:
        raise HTTPException(status_code=404, detail="Chat not found")
    return updated


@app.post("/chats/{chat_id}/title", tags=["Chat Management"])
def generate_title_for_chat(
    chat_id: int,
    body: dict,
    current_user: models.User = Depends(auth.get_current_user),
):
    """Generate a title from the first user message (assistant-ui ThreadList adapter)."""
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")

    messages = body.get("messages") or []
    user_text = ""
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                user_text = content
            elif isinstance(content, list):
                user_text = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
                )
            break
    if not user_text:
        user_text = chat.title or "New Chat"

    title = generate_chat_title(user_text)
    crud.update_chat_title(chat_id, title)
    return {"title": title}


@app.get("/chats/{chat_id}/aui-messages", tags=["Messages"])
def get_aui_messages(chat_id: int, current_user: models.User = Depends(auth.get_current_user)):
    """
    Return ThreadMessageLike[] reconstructed from MessageHistory
    (includes tool-call parts + results for assistant-ui history reload).
    """
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return message_history_to_thread_messages(str(chat_id))


@app.post("/assistant/chat", tags=["Assistant UI"])
async def assistant_chat(
    request: Request,
    current_user: models.User | None = Depends(auth.get_optional_user),
):
    """
    Data-stream protocol endpoint for assistant-ui (`useDataStreamRuntime`).

    Body: { messages, threadId?, ... }
    Response: text/plain data-stream v1 (x-vercel-ai-data-stream: v1)
    """
    from .chat_gate import gate_chat_request
    from .device_id import attach_device_cookie

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages") or []
    # Prefer explicit threadId; fall back to fields some clients send
    thread_id = body.get("threadId") or body.get("thread_id") or body.get("chatId")

    # Extract last user text from assistant-ui / AI SDK message shapes
    user_message = ""
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            user_message = content
        elif isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict):
                    if p.get("type") == "text":
                        parts.append(p.get("text") or "")
                    elif "text" in p:
                        parts.append(str(p["text"]))
            user_message = "".join(parts)
        break

    if not user_message.strip():
        raise HTTPException(status_code=400, detail="No user message found")

    # Scope + quota + device id (cookie attached on every response path)
    gate = gate_chat_request(
        request=request,
        response=None,
        message=user_message,
        user=current_user,
    )
    if not gate.allowed:
        status = gate.http_status or 400
        content: dict = {
            "detail": gate.refusal,
            "error": gate.error_code or "forbidden",
        }
        if gate.quota_status is not None:
            q = gate.quota_status
            content.update(
                {
                    "used": q.used,
                    "limit": q.limit,
                    "remaining": q.remaining,
                    "window_hours": q.window_hours,
                    "resets_at": q.resets_at.isoformat() if q.resets_at else None,
                    "byok": q.byok,
                    "message": gate.refusal,
                }
            )
        resp = JSONResponse(status_code=status, content=content)
        if gate.device:
            attach_device_cookie(resp, gate.device, request=request)
        return resp

    is_guest = current_user is None
    session_id: str | None = None
    chat = None

    if is_guest:
        # Keep multi-turn memory + prompt-cache affinity without a DB chat row.
        # Prefer the client threadId (guest-...); mint one if missing.
        if thread_id and str(thread_id).strip():
            session_id = str(thread_id).strip()
        else:
            session_id = f"guest-{uuid.uuid4()}"
        if gate.agent_ctx:
            # No numeric chat_id for guests
            gate.agent_ctx.chat_id = None
        logger.info("[assistant/chat] guest session_id=%s", session_id)
    else:
        if thread_id is None or str(thread_id).startswith("guest-"):
            # The frontend must always send a threadId (created via POST /chats first).
            # Silently creating a chat here would produce a duplicate sidebar entry
            # whenever the frontend's remoteId hadn't propagated before the first message.
            raise HTTPException(
                status_code=400,
                detail="threadId is required for authenticated users. Create a chat via POST /chats first.",
            )
        else:
            try:
                chat_id_int = int(thread_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid threadId")
            chat = crud.get_chat(chat_id_int)
            if not chat or chat.user_id != current_user.id:
                raise HTTPException(status_code=404, detail="Chat not found")
            session_id = str(chat.id)
            logger.info("[assistant/chat] continuing chat_id=%s", chat.id)
            if gate.agent_ctx:
                gate.agent_ctx.chat_id = chat.id
            if not chat.title or chat.title in ("New Chat", "Untitled"):
                title_text = generate_chat_title(user_message, agent_ctx=gate.agent_ctx)
                crud.update_chat_title(chat.id, title_text)

        crud.create_message(chat_id=chat.id, sender="user", content=user_message)

    user_context = build_user_context(current_user)
    agent_input = {"input": user_message}
    cancel_event = asyncio.Event()

    async def generate():
        full_response = ""
        try:
            if chat is not None:
                yield ds.data([{"type": "thread-id", "threadId": str(chat.id)}])
            elif is_guest and session_id:
                yield ds.data([{"type": "thread-id", "threadId": session_id}])

            async for line in stream_memory_agent_data_stream(
                agent_input,
                session_id=session_id,
                user_context=user_context,
                cancel_event=cancel_event,
                agent_ctx=gate.agent_ctx,
            ):
                if await request.is_disconnected():
                    cancel_event.set()
                    break
                if line.startswith("0:"):
                    try:
                        full_response += json.loads(line[2:])
                    except Exception:
                        pass
                yield line
        except Exception as e:
            logger.error(f"[assistant/chat] stream failed: {e}", exc_info=True)
            yield ds.error(str(e))
        finally:
            if chat is not None and full_response:
                try:
                    crud.create_message(chat_id=chat.id, sender="assistant", content=full_response)
                except Exception as e:
                    logger.error(f"[assistant/chat] failed to persist assistant message: {e}")

    streaming = StreamingResponse(
        generate(), headers=ds.DATA_STREAM_HEADERS, media_type="text/plain; charset=utf-8"
    )
    if gate.device:
        attach_device_cookie(streaming, gate.device, request=request)
    return streaming


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


# =====================
# WebSocket Chat Endpoints
# =====================

async def authenticate_websocket(websocket: WebSocket) -> models.User | None:
    """
    Authenticate a WebSocket connection using the token from query params or cookies.
    Returns the user if authenticated, None otherwise.
    """
    # Try to get token from query params first, then cookies
    token = websocket.query_params.get("token")
    if not token:
        token = websocket.cookies.get("access_token")
    
    if not token:
        return None
    
    try:
        # Remove "Bearer " prefix if present
        if token.startswith("Bearer "):
            token = token[7:]
        
        # Verify token and get payload (sync function, not async)
        payload = auth.verify_access_token(token)
        
        # Get user from database using oauth_id (sub claim)
        oauth_id = payload.get("sub")
        if not oauth_id:
            return None
        
        user = crud.get_user_by_oauth_id(oauth_id)
        return user
    except Exception as e:
        logger.error(f"WebSocket authentication failed: {e}")
        return None


@app.websocket("/ws/chat/new")
async def websocket_new_chat(websocket: WebSocket):
    """
    WebSocket endpoint for creating a new chat and streaming the response.
    
    Client sends: { type: "message", content: "..." } or { type: "stop" }
    Server sends: { type: "chat", id: "...", title: "..." }
                  { type: "status", status: "thinking" | "tool_call", tool?: "..." }
                  { type: "token", content: "..." }
                  { type: "done", message_id: "..." }
                  { type: "error", message: "..." }
    """
    await websocket.accept()
    
    # Authenticate — guests get None
    current_user = await authenticate_websocket(websocket)
    is_guest = current_user is None
    
    # Allow guest connections (no 4001 close)
    
    cancel_event = asyncio.Event()
    
    try:
        # Wait for the first message
        data = await websocket.receive_json()
        
        if data.get("type") != "message" or not data.get("content"):
            await websocket.send_json({"type": "error", "message": "Invalid message format"})
            await websocket.close()
            return
        
        user_message = data["content"]
        
        # Generate title
        title_text = generate_chat_title(user_message)
        
        if is_guest:
            import uuid
            guest_session_id = f"guest-{uuid.uuid4()}"
            
            logger.info(f"[WEBSOCKET NEW] Guest session: {guest_session_id}")
            
            # Send chat metadata (ephemeral)
            await websocket.send_json({"type": "chat", "id": guest_session_id, "title": title_text})
            
            user_context = build_user_context(None)
            agent_input = {"input": user_message}
            
            # Create a task to listen for stop commands
            async def listen_for_stop():
                try:
                    while True:
                        msg = await websocket.receive_json()
                        if msg.get("type") == "stop":
                            cancel_event.set()
                            break
                except WebSocketDisconnect:
                    cancel_event.set()
                except Exception:
                    pass
            
            stop_listener = asyncio.create_task(listen_for_stop())
            
            full_response = ""
            try:
                async for event in stream_memory_agent_with_status(
                    agent_input, 
                    session_id=guest_session_id,
                    user_context=user_context,
                    cancel_event=cancel_event
                ):
                    if event["type"] == "token":
                        full_response += event["content"]
                    await websocket.send_json(event)
                    
                    if event["type"] in ("done", "error"):
                        break
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected during streaming for guest session {guest_session_id}")
            finally:
                stop_listener.cancel()
            
            # Send final done for guest (no message_id since not persisted)
            if full_response and not cancel_event.is_set():
                try:
                    await websocket.send_json({"type": "done", "message_id": guest_session_id})
                except:
                    pass
        else:
            # Authenticated user: persist to DB
            chat = crud.create_chat(user_id=current_user.id, title=title_text)
            if not chat:
                await websocket.send_json({"type": "error", "message": "Failed to create chat"})
                await websocket.close()
                return
            
            logger.info(f"[WEBSOCKET NEW] Created new chat_id={chat.id}, session_id={str(chat.id)}, user_id={current_user.id}")
            
            # Send chat metadata
            await websocket.send_json({"type": "chat", "id": str(chat.id), "title": title_text})
            
            # Store user message
            crud.create_message(chat_id=chat.id, sender="user", content=user_message)
            
            # Build user context
            user_context = build_user_context(current_user)
            agent_input = {"input": user_message}
            
            # Create a task to listen for stop commands
            async def listen_for_stop():
                try:
                    while True:
                        msg = await websocket.receive_json()
                        if msg.get("type") == "stop":
                            cancel_event.set()
                            break
                except WebSocketDisconnect:
                    cancel_event.set()
                except Exception:
                    pass
            
            # Start listening for stop commands in background
            stop_listener = asyncio.create_task(listen_for_stop())
            
            # Stream the agent response
            full_response = ""
            try:
                async for event in stream_memory_agent_with_status(
                    agent_input, 
                    session_id=str(chat.id), 
                    user_context=user_context,
                    cancel_event=cancel_event
                ):
                    if event["type"] == "token":
                        full_response += event["content"]
                    await websocket.send_json(event)
                    
                    if event["type"] in ("done", "error"):
                        break
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected during streaming for chat {chat.id}")
            finally:
                stop_listener.cancel()
            
            # Store the complete assistant message
            if full_response:
                assistant_msg = crud.create_message(chat_id=chat.id, sender="assistant", content=full_response)
                # Send final done with message_id if not already sent
                if not cancel_event.is_set():
                    try:
                        await websocket.send_json({"type": "done", "message_id": str(assistant_msg.id)})
                    except:
                        pass
    
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json(classify_openrouter_error(e))
        except:
            pass


@app.websocket("/ws/chat/{chat_id}")
async def websocket_existing_chat(websocket: WebSocket, chat_id: int):
    """
    WebSocket endpoint for sending messages to an existing chat.
    
    Client sends: { type: "message", content: "..." } or { type: "stop" }
    Server sends: { type: "status", status: "thinking" | "tool_call", tool?: "..." }
                  { type: "token", content: "..." }
                  { type: "done", message_id: "..." }
                  { type: "error", message: "..." }
    """
    await websocket.accept()
    
    # Authenticate
    current_user = await authenticate_websocket(websocket)
    if not current_user:
        await websocket.send_json({"type": "error", "message": "Unauthorized"})
        await websocket.close(code=4001)
        return
    
    # Verify chat ownership
    chat = crud.get_chat(chat_id)
    if not chat or chat.user_id != current_user.id:
        await websocket.send_json({"type": "error", "message": "Chat not found"})
        await websocket.close(code=4004)
        return
    
    logger.info(f"[WEBSOCKET EXISTING] chat_id={chat_id}, session_id={str(chat.id)}, user_id={current_user.id}")
    
    cancel_event = asyncio.Event()
    
    try:
        while True:
            # Wait for message
            data = await websocket.receive_json()
            
            if data.get("type") == "stop":
                cancel_event.set()
                continue
            
            if data.get("type") != "message" or not data.get("content"):
                await websocket.send_json({"type": "error", "message": "Invalid message format"})
                continue
            
            # Reset cancel event for new message
            cancel_event.clear()
            
            user_message = data["content"]
            
            # Store user message
            crud.create_message(chat_id=chat.id, sender="user", content=user_message)
            
            # Build user context
            user_context = build_user_context(current_user)
            agent_input = {"input": user_message}
            
            # Create a task to listen for stop commands during this response
            stop_received = asyncio.Event()
            
            async def listen_for_stop():
                try:
                    while not stop_received.is_set():
                        msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                        if msg.get("type") == "stop":
                            cancel_event.set()
                            stop_received.set()
                            break
                except asyncio.TimeoutError:
                    pass
                except WebSocketDisconnect:
                    cancel_event.set()
                    stop_received.set()
                except Exception:
                    pass
            
            # Stream the agent response
            full_response = ""
            try:
                async for event in stream_memory_agent_with_status(
                    agent_input, 
                    session_id=str(chat.id), 
                    user_context=user_context,
                    cancel_event=cancel_event
                ):
                    # Check for stop in between events
                    try:
                        # Non-blocking check for stop message
                        msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
                        if msg.get("type") == "stop":
                            cancel_event.set()
                    except asyncio.TimeoutError:
                        pass
                    except Exception:
                        pass
                    
                    if event["type"] == "token":
                        full_response += event["content"]
                    await websocket.send_json(event)
                    
                    if event["type"] in ("done", "error"):
                        break
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected during streaming for chat {chat_id}")
                return
            
            # Store the complete assistant message
            if full_response:
                assistant_msg = crud.create_message(chat_id=chat.id, sender="assistant", content=full_response)
                # Send final done with message_id if not already sent
                if not cancel_event.is_set():
                    try:
                        await websocket.send_json({"type": "done", "message_id": str(assistant_msg.id)})
                    except:
                        pass
            
            stop_received.set()  # Signal to stop listener
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for chat {chat_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json(classify_openrouter_error(e))
        except:
            pass
import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.backends import RSAKey

from . import models
from .logging_config import get_logger

logger = get_logger(__name__)

# =============================================================================
# IITD OAuth Configuration
# =============================================================================

AUTH_BASE_URL = "https://auth.devclub.in"
AUTHORIZE_ENDPOINT = f"{AUTH_BASE_URL}/api/oauth/authorize"
TOKEN_ENDPOINT = f"{AUTH_BASE_URL}/api/oauth/token"
USERINFO_ENDPOINT = f"{AUTH_BASE_URL}/api/oauth/userinfo"
JWKS_URL = f"{AUTH_BASE_URL}/api/oauth/.well-known/jwks.json"

DEVCLUB_CLIENT_ID = os.environ.get("CLIENT_ID")
DEVCLUB_CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
DEFAULT_SCOPES = "openid profile email hostel entry_number"

DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"

# JWKS cache (refreshed periodically)
_jwks_cache: Optional[dict] = None
_jwks_cache_time: Optional[datetime] = None
JWKS_CACHE_TTL_MINUTES = 60


# =============================================================================
# PKCE Helpers
# =============================================================================

def generate_pkce_pair() -> Tuple[str, str]:
    """
    Generate a PKCE code_verifier and code_challenge pair.
    
    Returns:
        Tuple of (code_verifier, code_challenge)
        - code_verifier: random 32-byte base64url string
        - code_challenge: SHA256 hash of verifier, base64url encoded
    """
    # Generate random 32 bytes and encode as base64url
    code_verifier = secrets.token_urlsafe(32)
    
    # Compute SHA256 hash and encode as base64url
    digest = hashlib.sha256(code_verifier.encode('ascii')).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
    
    return code_verifier, code_challenge


def email_to_kerberos(email: str) -> Optional[str]:
    """
    Convert email number to kerberos ID.
    Args:
        email: The IITD Webmail ID
        
    Returns:
        Kerberos ID like "me2241111" or None if invalid
    """
    if not email:
        logger.warning("[email_to_kerberos] email is None or empty")
        return None    
    try:        
        kerberos = email.split('@')[0]
        logger.debug(f"[email_to_kerberos] Derived kerberos: {kerberos}")
        return kerberos
    except (IndexError, AttributeError) as e:
        logger.error(f"[email_to_kerberos] Error deriving kerberos: {e}")
        return None


# =============================================================================
# OAuth State Management
# =============================================================================

def create_oauth_state(redirect_uri: str) -> Tuple[str, str]:
    """
    Create OAuth state with PKCE parameters and store in database.
    
    Args:
        redirect_uri: The URL to redirect to after authentication
        
    Returns:
        Tuple of (state, authorize_url)
    """
    from . import crud
    
    if not DEVCLUB_CLIENT_ID:
        raise ValueError("CLIENT_ID environment variable not set")
    
    # Generate PKCE pair
    code_verifier, code_challenge = generate_pkce_pair()
    
    # Generate random state for CSRF protection
    state = secrets.token_urlsafe(16)
    
    # Store in database
    crud.create_oauth_state(state, code_verifier, redirect_uri)
    logger.info(f"[create_oauth_state] Created OAuth state={state} for redirect_uri={redirect_uri}")
    
    # Build authorization URL
    params = {
        "response_type": "code",
        "client_id": DEVCLUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": DEFAULT_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    
    authorize_url = f"{AUTHORIZE_ENDPOINT}?{urlencode(params)}"
    logger.info(f"[create_oauth_state] Authorize URL built: {authorize_url}")
    
    return state, authorize_url


# =============================================================================
# Token Exchange
# =============================================================================

async def exchange_code_for_token(code: str, state: str) -> Tuple[str, dict]:
    """
    Exchange authorization code for access token using PKCE.
    
    Args:
        code: Authorization code from OAuth callback
        state: State parameter for CSRF validation and PKCE lookup
        
    Returns:
        Tuple of (access_token, user_info dict)
        
    Raises:
        HTTPException: If exchange fails
    """
    from . import crud
    
    if not DEVCLUB_CLIENT_ID or not DEVCLUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth credentials not configured"
        )
    
    logger.info(f"[exchange_code_for_token] Exchanging code for token, state={state}")
    
    # Retrieve and delete PKCE state (one-time use)
    oauth_state = crud.get_and_delete_oauth_state(state)
    if not oauth_state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter"
        )
    
    # Exchange code for token
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TOKEN_ENDPOINT,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": oauth_state.redirect_uri,
                    "client_id": DEVCLUB_CLIENT_ID,
                    "client_secret": DEVCLUB_CLIENT_SECRET,
                    "code_verifier": oauth_state.code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            
            if response.status_code != 200:
                error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                error_msg = error_data.get("error_description", error_data.get("error", "Token exchange failed"))
                logger.error(f"[exchange_code_for_token] Token exchange failed: {response.status_code} - {error_msg}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Authentication failed: {error_msg}"
                )
            
            token_data = response.json()
            access_token = token_data.get("access_token")
            
            if not access_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="No access token in response"
                )
            
            # Extract user info from token response or fetch from userinfo endpoint
            user_info = token_data.get("user_data")
            if not user_info:
                # Fetch from userinfo endpoint
                user_info = await fetch_user_info(access_token)
            
            logger.info(f"[exchange_code_for_token] User info received for sub={user_info.get('sub', 'unknown')}")
            
            return access_token, user_info
            
    except httpx.RequestError as e:
        logger.error(f"[exchange_code_for_token] Request failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to communicate with OAuth server"
        )


async def fetch_user_info(access_token: str) -> dict:
    """
    Fetch user information from the OAuth userinfo endpoint.
    
    Args:
        access_token: Valid OAuth access token
        
    Returns:
        User info dictionary
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            
            if response.status_code == 200:
                logger.info("[fetch_user_info] User info fetched successfully")
                return response.json()
            else:
                logger.error(f"[fetch_user_info] Failed: {response.status_code}")
                return {}
                
    except httpx.RequestError as e:
        logger.error(f"[fetch_user_info] Request failed: {e}")
        return {}


# =============================================================================
# JWKS and Token Verification
# =============================================================================

async def get_jwks() -> dict:
    """
    Fetch and cache JWKS (JSON Web Key Set) from the OAuth server.
    
    Returns:
        JWKS dictionary with keys
    """
    global _jwks_cache, _jwks_cache_time
    
    # Check if cache is valid
    if _jwks_cache and _jwks_cache_time:
        age = datetime.utcnow() - _jwks_cache_time
        if age < timedelta(minutes=JWKS_CACHE_TTL_MINUTES):
            return _jwks_cache
    
    # Fetch fresh JWKS
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(JWKS_URL)
            if response.status_code == 200:
                _jwks_cache = response.json()
                _jwks_cache_time = datetime.utcnow()
                logger.info("[get_jwks] JWKS fetched and cached")
                return _jwks_cache
            else:
                logger.error(f"[get_jwks] Fetch failed: {response.status_code}")
                # Return cached version if available
                if _jwks_cache:
                    return _jwks_cache
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to fetch JWKS"
                )
    except httpx.RequestError as e:
        logger.error(f"[get_jwks] Request failed: {e}")
        if _jwks_cache:
            return _jwks_cache
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch JWKS"
        )


def get_jwks_sync() -> dict:
    """
    Synchronous version of get_jwks for use in sync contexts.
    Uses cached JWKS or fetches synchronously.
    """
    global _jwks_cache, _jwks_cache_time
    
    # Check if cache is valid
    if _jwks_cache and _jwks_cache_time:
        age = datetime.utcnow() - _jwks_cache_time
        if age < timedelta(minutes=JWKS_CACHE_TTL_MINUTES):
            return _jwks_cache
    
    # Fetch fresh JWKS synchronously
    try:
        with httpx.Client() as client:
            response = client.get(JWKS_URL)
            if response.status_code == 200:
                _jwks_cache = response.json()
                _jwks_cache_time = datetime.utcnow()
                return _jwks_cache
    except httpx.RequestError as e:
        logger.error(f"[get_jwks_sync] Request failed: {e}")
    
    if _jwks_cache:
        return _jwks_cache
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Failed to fetch JWKS"
    )


def verify_access_token(token: str) -> dict:
    """
    Verify an OAuth access token using JWKS.
    
    Args:
        token: JWT access token from OAuth server
        
    Returns:
        Decoded token payload
        
    Raises:
        HTTPException: If token is invalid
    """
    try:
        # Get JWKS
        jwks = get_jwks_sync()
        
        # Decode token header to get key ID (kid)
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        
        # Find the matching key
        key = None
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key = k
                break
        
        if not key:
            # Try first key if no kid match
            keys = jwks.get("keys", [])
            if keys:
                key = keys[0]
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="No valid signing key found"
                )
        
        # Verify and decode the token
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=DEVCLUB_CLIENT_ID,
            issuer=AUTH_BASE_URL,
            options={"verify_aud": False}  # Some OAuth servers don't include audience
        )
        
        return payload
        
    except JWTError as e:
        logger.error(f"[verify_access_token] Token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )


# =============================================================================
# FastAPI Dependencies
# =============================================================================

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())) -> models.User:
    """
    FastAPI dependency to get the current authenticated user.
    
    Verifies the OAuth access token and returns the corresponding user.
    """
    # Demo mode: return a fake user for presentations
    if DEMO_MODE:
        token = credentials.credentials
        if token and token.startswith("demo"):
            from . import crud
            
            try:
                demo_user_info = {
                    "email": "demo@iitd.ac.in",
                    "name": "Demo User",
                    "sub": "demo_user_id",
                }
                demo_user = crud.get_or_create_user(demo_user_info)
                return demo_user
            except Exception as e:
                logger.error(f"[get_current_user] Demo user creation failed: {e}")
                return models.User(
                    id=1,
                    email="demo@iitd.ac.in",
                    name="Demo User",
                    role="user"
                )
    
    # Normal authentication flow
    token = credentials.credentials
    
    # Verify the OAuth access token using JWKS
    payload = verify_access_token(token)
    
    # Extract user identifier
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing subject"
        )
    
    # Look up user by oauth_id
    from . import crud
    user = crud.get_user_by_oauth_id(sub)
    
    if not user:
        # User authenticated but not in our database
        # This shouldn't happen in normal flow (user created at callback)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found. Please sign in again."
        )
    
    return user


def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False))) -> models.User | None:
    """
    FastAPI dependency that returns the current user if authenticated, or None for guests.
    
    Unlike get_current_user(), this does NOT raise 401 — it silently returns None
    when no token is provided or the token is invalid.
    """
    if credentials is None:
        return None
    
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None


def get_current_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    """Dependency that ensures the current user has the 'admin' role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

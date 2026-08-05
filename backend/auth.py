"""DevClub / IITD OAuth (OIDC) — https://auth.devclub.in/docs

Authorization-code + PKCE (S256) + client_secret_post.
After a successful IdP exchange we mint our own HS256 API JWT so the
frontend keeps using Bearer tokens against this backend.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt

from . import models
from .logging_config import get_logger

logger = get_logger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Prefer CLIENT_ID / CLIENT_SECRET (existing); accept OIDC_* aliases from the docs
DEVCLUB_CLIENT_ID = os.environ.get("CLIENT_ID") or os.environ.get("OIDC_CLIENT_ID")
DEVCLUB_CLIENT_SECRET = os.environ.get("CLIENT_SECRET") or os.environ.get("OIDC_CLIENT_SECRET")

OIDC_DISCOVERY_URL = os.environ.get(
    "OIDC_DISCOVERY_URL",
    "https://auth.devclub.in/api/oauth/.well-known/openid-configuration",
)
# Fallback issuer if discovery is unreachable
OIDC_ISSUER_FALLBACK = os.environ.get("OIDC_ISSUER", "https://auth.devclub.in")

# Scopes supported by the IdP (openid-configuration scopes_supported)
DEFAULT_SCOPES = os.environ.get(
    "OIDC_SCOPE",
    "openid profile email hostel entry_number kerberos",
)

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXP_MINUTES = int(os.environ.get("JWT_EXP_MINUTES", "1440"))

DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"

# Hardcoded fallbacks matching current discovery document
_FALLBACK_ENDPOINTS = {
    "issuer": OIDC_ISSUER_FALLBACK,
    "authorization_endpoint": f"{OIDC_ISSUER_FALLBACK.rstrip('/')}/api/oauth/authorize",
    "token_endpoint": f"{OIDC_ISSUER_FALLBACK.rstrip('/')}/api/oauth/token",
    "userinfo_endpoint": f"{OIDC_ISSUER_FALLBACK.rstrip('/')}/api/oauth/userinfo",
    "jwks_uri": f"{OIDC_ISSUER_FALLBACK.rstrip('/')}/api/oauth/.well-known/jwks.json",
}

_discovery_cache: Optional[dict] = None
_discovery_cache_time: Optional[datetime] = None
_jwks_cache: Optional[dict] = None
_jwks_cache_time: Optional[datetime] = None
CACHE_TTL = timedelta(minutes=60)


# =============================================================================
# OIDC discovery / JWKS
# =============================================================================

def get_oidc_config(force_refresh: bool = False) -> dict:
    """Return OIDC discovery document (cached)."""
    global _discovery_cache, _discovery_cache_time

    if (
        not force_refresh
        and _discovery_cache
        and _discovery_cache_time
        and datetime.utcnow() - _discovery_cache_time < CACHE_TTL
    ):
        return _discovery_cache

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(OIDC_DISCOVERY_URL)
            response.raise_for_status()
            _discovery_cache = response.json()
            _discovery_cache_time = datetime.utcnow()
            logger.info("[get_oidc_config] Discovery document loaded from %s", OIDC_DISCOVERY_URL)
            return _discovery_cache
    except Exception as e:
        logger.warning("[get_oidc_config] Discovery failed (%s); using fallbacks", e)
        if _discovery_cache:
            return _discovery_cache
        return dict(_FALLBACK_ENDPOINTS)


def get_jwks_sync(force_refresh: bool = False) -> dict:
    """Fetch and cache JWKS from the IdP."""
    global _jwks_cache, _jwks_cache_time

    if (
        not force_refresh
        and _jwks_cache
        and _jwks_cache_time
        and datetime.utcnow() - _jwks_cache_time < CACHE_TTL
    ):
        return _jwks_cache

    jwks_uri = get_oidc_config().get("jwks_uri") or _FALLBACK_ENDPOINTS["jwks_uri"]
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(jwks_uri)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_time = datetime.utcnow()
            logger.info("[get_jwks_sync] JWKS fetched from %s", jwks_uri)
            return _jwks_cache
    except Exception as e:
        logger.error("[get_jwks_sync] Failed: %s", e)
        if _jwks_cache:
            return _jwks_cache
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch JWKS from OAuth server",
        )


def _rsa_key_for_token(token: str):
    """Resolve the RSA key from JWKS for a JWT's kid."""
    jwks = get_jwks_sync()
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    keys = jwks.get("keys") or []

    selected = None
    for k in keys:
        if kid and k.get("kid") == kid:
            selected = k
            break
    if selected is None and keys:
        selected = keys[0]
    if selected is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No valid signing key found",
        )
    return jwk.construct(selected)


def verify_id_token(id_token: str) -> dict:
    """Verify the OIDC id_token (RS256) against JWKS."""
    try:
        key = _rsa_key_for_token(id_token)
        issuer = get_oidc_config().get("issuer") or OIDC_ISSUER_FALLBACK
        # Audience may be omitted by some deployments; verify when present.
        options = {"verify_aud": bool(DEVCLUB_CLIENT_ID)}
        payload = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=DEVCLUB_CLIENT_ID,
            issuer=issuer,
            options=options,
        )
        return payload
    except JWTError as e:
        logger.error("[verify_id_token] Failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired id_token",
        )


# =============================================================================
# PKCE + helpers
# =============================================================================

def generate_pkce_pair() -> Tuple[str, str]:
    """Return (code_verifier, S256 code_challenge)."""
    code_verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def email_to_kerberos(email: str) -> Optional[str]:
    if not email:
        return None
    try:
        return email.split("@")[0]
    except (IndexError, AttributeError) as e:
        logger.error("[email_to_kerberos] Error: %s", e)
        return None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Mint an HS256 JWT for this API (returned to the frontend as access_token)."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=JWT_EXP_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_access_token(token: str) -> dict:
    """Verify our API JWT (not the IdP access token)."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        logger.error("[verify_access_token] Failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


# =============================================================================
# Authorize URL / token exchange
# =============================================================================

def create_oauth_state(redirect_uri: str) -> Tuple[str, str]:
    """
    Create PKCE state and return (state, authorize_url).
    Same API shape used by GET /auth/signin-url.
    """
    from . import crud

    if not DEVCLUB_CLIENT_ID:
        raise ValueError("CLIENT_ID (or OIDC_CLIENT_ID) environment variable not set")

    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    crud.create_oauth_state(state, code_verifier, redirect_uri)
    logger.info("[create_oauth_state] state=%s redirect_uri=%s", state, redirect_uri)

    authorize_endpoint = (
        get_oidc_config().get("authorization_endpoint")
        or _FALLBACK_ENDPOINTS["authorization_endpoint"]
    )
    params = {
        "response_type": "code",
        "client_id": DEVCLUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": DEFAULT_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{authorize_endpoint}?{urlencode(params)}"
    return state, authorize_url


def _merge_user_claims(id_claims: dict, userinfo: dict) -> dict:
    """Merge id_token claims with userinfo (userinfo wins on conflict)."""
    merged: dict[str, Any] = {}
    merged.update(id_claims or {})
    merged.update({k: v for k, v in (userinfo or {}).items() if v is not None})
    # Prefer explicit kerberos claim; otherwise derive from email
    if not merged.get("kerberos") and merged.get("email"):
        merged["kerberos"] = email_to_kerberos(merged["email"])
    return merged


async def fetch_user_info(access_token: str) -> dict:
    """GET userinfo with the IdP access token."""
    userinfo_endpoint = (
        get_oidc_config().get("userinfo_endpoint")
        or _FALLBACK_ENDPOINTS["userinfo_endpoint"]
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code == 200:
                return response.json()
            logger.error("[fetch_user_info] status=%s body=%s", response.status_code, response.text[:300])
            return {}
    except httpx.RequestError as e:
        logger.error("[fetch_user_info] Request failed: %s", e)
        return {}


async def exchange_code_for_token(code: str, state: str) -> Tuple[str, dict]:
    """
    Exchange authorization code for tokens (PKCE + client_secret_post).

    Returns:
        (idp_access_token, user_info) — caller should mint the API JWT after
        get_or_create_user. Kept as Tuple[str, dict] for call-site compatibility.
    """
    from . import crud

    if not DEVCLUB_CLIENT_ID or not DEVCLUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth credentials not configured (CLIENT_ID / CLIENT_SECRET)",
        )

    oauth_state = crud.get_and_delete_oauth_state(state)
    if not oauth_state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter",
        )

    token_endpoint = (
        get_oidc_config().get("token_endpoint") or _FALLBACK_ENDPOINTS["token_endpoint"]
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                token_endpoint,
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
                error_data = {}
                try:
                    error_data = response.json()
                except Exception:
                    pass
                error_msg = error_data.get(
                    "error_description",
                    error_data.get("error", response.text[:200] or "Token exchange failed"),
                )
                logger.error(
                    "[exchange_code_for_token] Failed %s: %s",
                    response.status_code,
                    error_msg,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Authentication failed: {error_msg}",
                )

            token_data = response.json()
    except httpx.RequestError as e:
        logger.error("[exchange_code_for_token] Request failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to communicate with OAuth server",
        )

    idp_access_token = token_data.get("access_token")
    id_token = token_data.get("id_token")
    if not idp_access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No access_token in token response",
        )

    id_claims: dict = {}
    if id_token:
        id_claims = verify_id_token(id_token)
    else:
        logger.warning("[exchange_code_for_token] No id_token in response; relying on userinfo")

    userinfo = await fetch_user_info(idp_access_token)
    user_info = _merge_user_claims(id_claims, userinfo)

    if not user_info.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OAuth response missing subject (sub)",
        )

    logger.info(
        "[exchange_code_for_token] Authenticated sub=%s email=%s",
        user_info.get("sub"),
        user_info.get("email"),
    )
    return idp_access_token, user_info


# =============================================================================
# FastAPI dependencies
# =============================================================================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> models.User:
    """Resolve the authenticated user from our API Bearer JWT."""
    if DEMO_MODE:
        token = credentials.credentials
        if token and token.startswith("demo"):
            from . import crud

            try:
                return crud.get_or_create_user(
                    {
                        "email": "demo@iitd.ac.in",
                        "name": "Demo User",
                        "sub": "demo_user_id",
                    }
                )
            except Exception as e:
                logger.error("[get_current_user] Demo user failed: %s", e)
                return models.User(
                    id=1,
                    email="demo@iitd.ac.in",
                    name="Demo User",
                    role="user",
                )

    payload = verify_access_token(credentials.credentials)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing subject",
        )

    from . import crud

    user = crud.get_user_by_oauth_id(str(sub))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found. Please sign in again.",
        )
    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
) -> models.User | None:
    if credentials is None:
        return None
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None


def get_current_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user

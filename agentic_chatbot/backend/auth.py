from datetime import datetime, timedelta
import os
from typing import Optional

from jose import JWTError, jwt
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from . import models

# Secrets and settings
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-prod")
JWT_ALGO = "HS256"
JWT_EXP_MINUTES = int(os.environ.get("JWT_EXP_MINUTES", "60"))
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")


def verify_id_token(id_token_str: str) -> Optional[dict]:
    """Verify an OIDC id_token using google-auth. Returns basic user info dict on success.

    The function uses GOOGLE_CLIENT_ID env var as expected audience. If not set, verification will still attempt to validate but audience won't be enforced.
    """
    try:
        request = google_requests.Request()
        # pass audience if configured (recommended)
        audience = GOOGLE_CLIENT_ID if GOOGLE_CLIENT_ID else None
        id_info = google_id_token.verify_oauth2_token(id_token_str, request, audience)
        # id_info now contains verified token claims
        return {"email": id_info.get("email"), "name": id_info.get("name"), "picture": id_info.get("picture")}
    except Exception:
        return None


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXP_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGO)
    return encoded


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())) -> models.User:
    token = credentials.credentials
    payload = decode_token(token)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    try:
        user_id = int(sub)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user id in token")

    from sqlmodel import Session
    engine = models.get_engine()
    with Session(engine) as sess:
        usr = sess.get(models.User, user_id)
        if not usr:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return usr

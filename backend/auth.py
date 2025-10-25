from datetime import datetime, timedelta
import os
from typing import Optional

from jose import JWTError, jwt
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx

from . import models

# Secrets and settings
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-prod")
JWT_ALGO = "HS256"
JWT_EXP_MINUTES = int(os.environ.get("JWT_EXP_MINUTES", "1440"))
DEVCLUB_CLIENT_ID = os.environ.get("CLIENT_ID")
DEVCLUB_CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
DEVCLUB_AUTH_URL = "https://iitdoauth.vercel.app/api/auth/resource"


async def verify_devclub_code(auth_code: str, state: str) -> Optional[dict]:
    """Verify an authorization code with DevClub OAuth server. Returns user info dict on success.

    The function uses CLIENT_ID and CLIENT_SECRET env vars to authenticate with the DevClub OAuth server.
    """
    if not DEVCLUB_CLIENT_ID or not DEVCLUB_CLIENT_SECRET:
        return None
        
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                DEVCLUB_AUTH_URL,
                json={
                    "client_id": DEVCLUB_CLIENT_ID,
                    "client_secret": DEVCLUB_CLIENT_SECRET,
                    "auth_code": auth_code,
                    "state": state,
                    "grant_type": "authorization_code",
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                # Extract user info from the response
                user = data.get("user", {})
                return {
                    "email": user.get("email"),
                    "name": user.get("name"),
                    "picture": user.get("picture")
                }
            return None
    except Exception as e:
        print(f"DevClub OAuth verification failed: {e}")
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

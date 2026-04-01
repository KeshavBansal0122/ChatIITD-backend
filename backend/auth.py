from datetime import datetime, timedelta
import os
from typing import Optional
from urllib.parse import urlencode

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
DEVCLUB_AUTH_URL = "https://oauth.devclub.in/api/auth/resource"
DEVCLUB_SIGNIN_URL = "https://oauth.devclub.in/signin"
DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"


def get_oauth_signin_url(redirect_uri: str) -> str:
    """
    Generate the OAuth signin URL for DevClub authentication.
    
    Args:
        redirect_uri: The URL to redirect to after authentication
        
    Returns:
        Complete OAuth signin URL
    """
    if not DEVCLUB_CLIENT_ID:
        raise ValueError("CLIENT_ID environment variable not set")
    
    params = {
        "client_id": DEVCLUB_CLIENT_ID,
        "redirect_uri": redirect_uri
    }
    
    return f"{DEVCLUB_SIGNIN_URL}?{urlencode(params)}"


async def verify_devclub_code(auth_code: str, state: str) -> Optional[dict]:
    """Verify an authorization code with DevClub OAuth server. Returns user info dict on success.

    The function uses CLIENT_ID and CLIENT_SECRET env vars to authenticate with the DevClub OAuth server.
    Uses the new DevClub OAuth API at oauth.devclub.in with the updated response structure.
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
                # Extract user info from the new response structure
                user = data.get("user", {})
                return {
                    "id": user.get("id"),
                    "oauth_id": user.get("oauthId"),
                    "email": user.get("email"),
                    "name": user.get("name"),
                    "picture": None,  # Not provided in new response
                    "hostel": user.get("hostel"),
                    "kerberos": user.get("kerberos"),
                    "date_of_birth": user.get("dateOfBirth"),
                    "instagram_id": user.get("instagramId"),
                    "mobile_no": user.get("mobileNo"),
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
    # Demo mode: return a fake user for presentations
    if DEMO_MODE:
        # Check if we have a demo token (can be anything starting with "demo")
        token = credentials.credentials
        if token and token.startswith("demo"):
            # Return a fake user for demo purposes
            from . import crud
            
            # Try to get or create a demo user
            try:
                demo_user_info = {
                    "email": "demo@iitd.ac.in", 
                    "name": "Demo User", 
                    "picture": None
                }
                demo_user = crud.get_or_create_user(demo_user_info)
                return demo_user
            except Exception as e:
                print(f"Demo user creation failed: {e}")
                # Create a temporary user object for demo
                return models.User(
                    id=1,
                    email="demo@iitd.ac.in",
                    name="Demo User",
                    role="user"
                )
    
    # Normal authentication flow
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


def get_current_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    """Dependency that ensures the current user has the 'admin' role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

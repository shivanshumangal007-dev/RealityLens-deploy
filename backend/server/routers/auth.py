"""
routers/auth.py
───────────────
All authentication endpoints:
  POST /register
  POST /login
  GET  /me
  GET  /login/google
  GET  /auth/google/callback
"""
import os
import uuid

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import create_access_token, verify_password
from ..crud import create_user, get_user, get_user_by_email, get_user_from_userid
from ..database import get_db
from .deps import get_current_user_id

router = APIRouter(tags=["Authentication"])

# ── Pydantic schemas ──────────────────────────────────────────────────────────

class UserCredentials(BaseModel):
    username: str
    password: str
    email: str

class UserLogin(BaseModel):
    email: str
    password: str

# ── Standard auth endpoints ───────────────────────────────────────────────────

@router.post("/register")
async def register_user(credentials: UserCredentials, db: AsyncSession = Depends(get_db)):
    # 1. Check if username is taken
    if await get_user(db, credentials.username):
        raise HTTPException(status_code=400, detail="Username already exists")

    # 2. Check if email is already registered
    existing_user = await get_user_by_email(db, credentials.email)
    if existing_user:
        # If they exist but have no password, they previously registered via Google!
        if existing_user.password is None:
            raise HTTPException(
                status_code=400,
                detail="An account with this email exists via Google Login. Please sign in with Google.",
            )
        raise HTTPException(status_code=400, detail="Email already exists")

    # 3. Create a normal traditional user (with a hashed password)
    user = await create_user(db, credentials.username, credentials.password, credentials.email)
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer", "user_id": str(user.id)}


@router.post("/login")
async def login_user(credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    user = await get_user_by_email(db, credentials.email)

    # SECURITY SAFEGUARD: reject Google-only accounts before verify_password runs on a NULL hash
    if user and user.password is None:
        raise HTTPException(
            status_code=400,
            detail="This account uses Google Login. Please sign in with Google.",
        )

    if not user or not verify_password(credentials.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer", "user_id": str(user.id)}


@router.get("/me")
async def get_user_details(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    user = await get_user_from_userid(db, uuid.UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"username": user.username, "email": user.email}

# ── Google OAuth endpoints ────────────────────────────────────────────────────

google_oauth = OAuth()
google_oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


@router.get("/login/google", tags=["Google Authentication"])
async def google_login(request: Request):
    """Step A: Redirect user to Google sign-in."""
    redirect_uri = request.url_for("google_callback")
    return await google_oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback", tags=["Google Authentication"])
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Step B: Handle Google payload, link account, issue JWT."""
    try:
        token = await google_oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        if not user_info:
            raise HTTPException(status_code=400, detail="Failed to retrieve Google user details.")
    except OAuthError as error:
        raise HTTPException(status_code=400, detail=f"OAuth Handshake Error: {error.error}")

    email = user_info.get("email")
    name = user_info.get("name")

    user = await get_user_by_email(db, email)

    if not user:
        if not name:
            name = email.split("@")[0]
        user = await create_user(db=db, username=name, password=None, email=email)

    access_token = create_access_token(data={"sub": str(user.id)})
    frontend_url = f"realitylens://auth-callback?token={access_token}&user_id={user.id}"
    return RedirectResponse(url=frontend_url)

# ── Frontend Token Validation (React SDK) ─────────────────────────────────────

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

class GoogleTokenPayload(BaseModel):
    id_token: str

@router.post("/auth/google", tags=["Google Authentication"])
async def verify_google_token(payload: GoogleTokenPayload, db: AsyncSession = Depends(get_db)):
    """Handle id_token sent directly from the frontend React app."""
    try:
        # Verify the token with Google
        id_info = id_token.verify_oauth2_token(
            payload.id_token,
            google_requests.Request(),
            os.getenv("GOOGLE_CLIENT_ID")
        )
        
        email = id_info.get("email")
        name = id_info.get("name")
        
        if not email:
            raise HTTPException(status_code=400, detail="No email provided by Google")

        # Find or create user
        user = await get_user_by_email(db, email)
        if not user:
            if not name:
                name = email.split("@")[0]
            user = await create_user(db=db, username=name, password=None, email=email)
            
        # Generate our own JWT access token
        access_token = create_access_token(data={"sub": str(user.id)})
        return {"access_token": access_token, "token_type": "bearer", "user_id": str(user.id)}
        
    except ValueError:
        # Invalid token
        raise HTTPException(status_code=401, detail="Invalid Google token")

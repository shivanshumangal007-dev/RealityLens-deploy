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

from pydantic import functional_serializers
from pydantic import functional_serializers
import os
import uuid
import jwt

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import create_access_token, verify_password, ALGORITHM, SECRET_KEY
from ..crud import create_user, get_user, get_user_by_email, get_user_from_userid
from ..database import get_db
from ..Redis_Otp import redis_otp_db
from .deps import get_current_user_id
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from dotenv import load_dotenv
load_dotenv()

import os

router = APIRouter(tags=["Authentication"])

conf = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_FROM=os.getenv("MAIL_FROM"),
    MAIL_SERVER="smtp.gmail.com",
    MAIL_FROM_NAME="RealityLens",
    MAIL_PORT=465,                          # Correct port for Implicit SSL
    
    # --- FIX THE ENCRYPTION FLAGS HERE ---
    MAIL_STARTTLS=False,                    # Disable STARTTLS entirely for port 465
    MAIL_SSL_TLS=True,                      # Enable modern SSL/TLS
    # --------------------------------------
    
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

# ── Pydantic schemas ──────────────────────────────────────────────────────────

class UserCredentials(BaseModel):
    username: str
    password: str
    email: str

class UserLogin(BaseModel):
    email: str
    password: str

class VerifyOtp(BaseModel):
    otp:str
    token:str

# ── Standard auth endpoints ───────────────────────────────────────────────────

@router.post("/register")
async def register_user(credentials: UserCredentials, db: AsyncSession = Depends(get_db)):
    import json
    import random
    import uuid

    # 1. Check if username is taken
    if await get_user(db, credentials.username):
        raise HTTPException(status_code=400, detail="Username already exists")

    # 2. Check if email is already registered
    existing_user = await get_user_by_email(db, credentials.email)
    if existing_user:
        if existing_user.password is None:
            raise HTTPException(
                status_code=400,
                detail="An account with this email exists via Google Login. Please sign in with Google.",
            )
        raise HTTPException(status_code=400, detail="Email already exists")

    # Generate a 6-digit OTP
    otp_code = str(random.randint(100000, 999999))
    
    # Create a temporary token and store registration data in Redis
    temp_token = uuid.uuid4().hex
    reg_data = {
        "username": credentials.username,
        "password": credentials.password,
        "email": credentials.email,
        "otp": otp_code
    }
    
    await redis_otp_db.setex(f"pending_reg:{temp_token}", 300, json.dumps(reg_data))

    message = MessageSchema(
        subject="Your RealityLens OTP",
        recipients=[credentials.email],
        body=f"<p>Your OTP is <strong>{otp_code}</strong></p>",
        subtype=MessageType.html
    )
    fm = FastMail(conf)
    await fm.send_message(message)

    return {"access_token": temp_token, "token_type": "bearer", "status": "pending"}


@router.post("/login")
async def login_user(credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    import json
    import random
    import uuid

    user = await get_user_by_email(db, credentials.email)

    if user and user.password is None:
        raise HTTPException(
            status_code=400,
            detail="This account uses Google Login. Please sign in with Google.",
        )

    if not user or not verify_password(credentials.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Generate a 6-digit OTP
    otp_code = str(random.randint(100000, 999999))
    
    temp_token = uuid.uuid4().hex
    login_data = {
        "user_id": str(user.id),
        "otp": otp_code
    }
    
    await redis_otp_db.setex(f"pending_login:{temp_token}", 300, json.dumps(login_data))

    message = MessageSchema(
        subject="Your RealityLens OTP",
        recipients=[credentials.email],
        body=f"<p>Your OTP is <strong>{otp_code}</strong></p>",
        subtype=MessageType.html
    )
    fm = FastMail(conf)
    await fm.send_message(message)

    return {"access_token": temp_token, "token_type": "bearer", "status": "pending"}


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
        # Collect all valid client IDs (Electron/web + mobile)
        valid_client_ids = [
            cid for cid in [
                os.getenv("GOOGLE_CLIENT_ID"),          # Electron / Web
                os.getenv("GOOGLE_CLIENT_ID_MOBILE"),   # Mobile (Android/iOS)
            ] if cid
        ]

        # Verify signature & claims without audience lock so both clients pass
        id_info = id_token.verify_oauth2_token(
            payload.id_token,
            google_requests.Request(),
            audience=None,  # skip single-audience check
        )

        # Manually enforce audience against our whitelist
        if id_info.get("aud") not in valid_client_ids:
            raise HTTPException(
                status_code=401,
                detail="Token audience does not match any known client ID",
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




@router.post("/verify-otp")
async def verify_otp(cred: VerifyOtp, db: AsyncSession = Depends(get_db)):
    import json
    
    temp_token = cred.token
    
    # 1. Check if it's a pending registration
    reg_data_bytes = await redis_otp_db.get(f"pending_reg:{temp_token}")
    if reg_data_bytes:
        reg_data = json.loads(reg_data_bytes.decode("utf-8"))
        if reg_data["otp"] != cred.otp:
            raise HTTPException(status_code=400, detail="Invalid OTP code.")
            
        # Create user in DB now that OTP is verified
        user = await create_user(db, reg_data["username"], reg_data["password"], reg_data["email"])
        await redis_otp_db.delete(f"pending_reg:{temp_token}")
        
        # Issue real JWT
        access_token = create_access_token(data={"sub": str(user.id)})
        return {"access_token": access_token, "token_type": "bearer", "user_id": str(user.id), "message": "User registered and verified successfully"}

    # 2. Check if it's a pending login
    login_data_bytes = await redis_otp_db.get(f"pending_login:{temp_token}")
    if login_data_bytes:
        login_data = json.loads(login_data_bytes.decode("utf-8"))
        if login_data["otp"] != cred.otp:
            raise HTTPException(status_code=400, detail="Invalid OTP code.")
            
        user_id = login_data["user_id"]
        await redis_otp_db.delete(f"pending_login:{temp_token}")
        
        # Issue real JWT
        access_token = create_access_token(data={"sub": user_id})
        return {"access_token": access_token, "token_type": "bearer", "user_id": user_id, "message": "OTP verified successfully"}

    raise HTTPException(status_code=400, detail="OTP session expired or invalid. Please request a new OTP.")
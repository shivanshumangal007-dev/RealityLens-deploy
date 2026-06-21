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
import httpx
from dotenv import load_dotenv
import os
import hashlib
import base64
from ..services.analysis import get_user_plan
router = APIRouter(tags=["Authentication"])

load_dotenv()
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
MAIL_FROM = os.getenv("MAIL_FROM")

async def enforce_otp_rate_limit(email: str):
    # Check 1-minute cooldown
    cooldown = await redis_otp_db.get(f"otp_cooldown:{email}")
    if cooldown:
        raise HTTPException(status_code=429, detail="Please wait 1 minute before requesting another OTP.")

    # Check 5-OTP per hour limit
    count_str = await redis_otp_db.get(f"otp_count:{email}")
    if count_str and int(count_str) >= 5:
        raise HTTPException(status_code=429, detail="Maximum OTP requests reached. Please try again after an hour.")

    # Apply limits
    await redis_otp_db.setex(f"otp_cooldown:{email}", 60, "1")
    count = await redis_otp_db.incr(f"otp_count:{email}")
    if count == 1:
        await redis_otp_db.expire(f"otp_count:{email}", 3600)

async def send_otp_email(to_email: str, otp: str):
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }
    payload = {
        "sender": {"email": MAIL_FROM, "name": "RealityLens"},
        "to": [{"email": to_email}],
        "subject": "Your RealityLens OTP Code",
        "htmlContent": f"<html><body><p>A new perspective awaits! Verify your RealityLens account with code: <strong>{otp}</strong><br>This code expires in 5 minutes.</p></body></html>"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()

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
    
    await enforce_otp_rate_limit(credentials.email)
    
    # Send email
    try:
        await send_otp_email(credentials.email, otp_code)
    except Exception as e:
        print(f"Failed to send OTP email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send OTP email")
    
    # Create a temporary token and store registration data in Redis
    temp_token = uuid.uuid4().hex
    reg_data = {
        "username": credentials.username,
        "password": credentials.password,
        "email": credentials.email,
        "otp": otp_code
    }
    
    await redis_otp_db.setex(f"pending_reg:{temp_token}", 300, json.dumps(reg_data))

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
    
    await enforce_otp_rate_limit(credentials.email)
    
    # Send email
    try:
        await send_otp_email(credentials.email, otp_code)
    except Exception as e:
        print(f"Failed to send OTP email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send OTP email")
    
    temp_token = uuid.uuid4().hex
    login_data = {
        "user_id": str(user.id),
        "otp": otp_code
    }
    
    await redis_otp_db.setex(f"pending_login:{temp_token}", 300, json.dumps(login_data))

    return {"access_token": temp_token, "token_type": "bearer", "status": "pending"}


@router.get("/me")
async def get_user_details(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    user = await get_user_from_userid(db, uuid.UUID(user_id))
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    plan_info = await get_user_plan(user_id, db)

    return {"username": user.username, "email": user.email, "plan": plan_info}

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
    deep_link = f"realitylens://auth-callback?token={access_token}&user_id={user.id}"

    # Serve an intermediary HTML page that attempts the deep link and provides
    # fallback options (click-to-open button + copy token) for platforms like
    # Linux where custom protocol handlers are unreliable.
    from fastapi.responses import HTMLResponse
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>RealityLens – Signing you in…</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
           display:flex; align-items:center; justify-content:center; min-height:100vh;
           background:linear-gradient(135deg,#0f0c29,#302b63,#24243e); color:#e0e0e0; }}
    .card {{ background:rgba(255,255,255,.06); backdrop-filter:blur(12px);
             border:1px solid rgba(255,255,255,.12); border-radius:16px;
             padding:48px 40px; max-width:440px; text-align:center; }}
    h1 {{ font-size:22px; margin-bottom:8px; color:#fff; }}
    .sub {{ color:#aaa; margin-bottom:28px; font-size:14px; }}
    .spinner {{ width:40px; height:40px; margin:0 auto 24px;
               border:3px solid rgba(255,255,255,.15); border-top-color:#00e5ff;
               border-radius:50%; animation:spin .8s linear infinite; }}
    @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
    a.btn {{ display:inline-block; padding:12px 32px; border-radius:8px;
             background:linear-gradient(135deg,#00e5ff,#7c4dff); color:#fff;
             text-decoration:none; font-weight:600; font-size:15px;
             transition:opacity .2s; }}
    a.btn:hover {{ opacity:.85; }}
    .fallback {{ margin-top:28px; font-size:13px; color:#888; }}
    .token-box {{ margin-top:10px; background:rgba(0,0,0,.3); border:1px solid rgba(255,255,255,.1);
                  border-radius:8px; padding:10px 14px; word-break:break-all;
                  font-family:monospace; font-size:12px; color:#ccc;
                  max-height:80px; overflow-y:auto; user-select:all; cursor:text; }}
    .copy-btn {{ margin-top:8px; padding:6px 16px; border:1px solid rgba(255,255,255,.2);
                 border-radius:6px; background:transparent; color:#aaa; font-size:12px;
                 cursor:pointer; transition:color .2s,border-color .2s; }}
    .copy-btn:hover {{ color:#fff; border-color:rgba(255,255,255,.4); }}
    #status {{ margin-top:16px; font-size:13px; color:#4caf50; min-height:20px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="spinner" id="spinner"></div>
    <h1>Opening RealityLens…</h1>
    <p class="sub">If the app doesn't open automatically, click the button below.</p>
    <a class="btn" href="{deep_link}" id="open-btn">Open RealityLens</a>
    <p id="status"></p>
    <div class="fallback">
      <p>Still not working? Copy the token and paste it in the app:</p>
      <div class="token-box" id="token">{access_token}</div>
      <button class="copy-btn" onclick="copyToken()">Copy Token</button>
    </div>
  </div>
  <script>
    // 1. Try to fetch the local HTTP server running in the Electron app (fixes Linux AppImage)
    fetch('http://127.0.0.1:13456/ping')
      .then(function() {{
        // If the ping succeeds, the local server is running! Redirect there.
        window.location.href = "http://127.0.0.1:13456/callback?token={access_token}&user_id={user.id}";
      }})
      .catch(function() {{
        // 2. If it fails (mobile, or server not running), fallback to the original deep link
        setTimeout(function() {{
          window.location.href = "{deep_link}";
        }}, 500);
      }});

    function copyToken() {{
      var t = document.getElementById('token').textContent;
      navigator.clipboard.writeText(t).then(function() {{
        document.getElementById('status').textContent = '✓ Token copied to clipboard';
      }});
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)

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
        
        user_id = login_data["user_id"]
        user = await get_user_from_userid(db, uuid.UUID(user_id))

        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if login_data["otp"] != cred.otp:
            raise HTTPException(status_code=400, detail="Invalid OTP code.")
            
        await redis_otp_db.delete(f"pending_login:{temp_token}")
        
        # Issue real JWT
        access_token = create_access_token(data={"sub": user_id})
        return {"access_token": access_token, "token_type": "bearer", "user_id": user_id, "message": "OTP verified successfully"}

    raise HTTPException(status_code=400, detail="OTP session expired or invalid. Please request a new OTP.")
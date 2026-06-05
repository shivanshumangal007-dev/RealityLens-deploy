from datetime import datetime, timedelta, timezone
import bcrypt
import jwt
import os
import hashlib

SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-this-as-you-will")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days

def _prepare_password(password: str) -> bytes:
    """Pre-hash with SHA-256 if >71 bytes so bcrypt never sees >72 bytes."""
    pwd_bytes = password.encode("utf-8")
    if len(pwd_bytes) > 71:
        # SHA-256 hexdigest is always 64 chars = 64 bytes, safe for bcrypt
        pwd_bytes = hashlib.sha256(pwd_bytes).hexdigest().encode("utf-8")
    return pwd_bytes

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(_prepare_password(plain_password), hashed_password.encode("utf-8"))

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(_prepare_password(password), bcrypt.gensalt()).decode("utf-8")

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

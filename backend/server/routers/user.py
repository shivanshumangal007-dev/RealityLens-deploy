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
from .auth import send_otp_email
from ..auth import get_password_hash
import random
import json

router = APIRouter(tags=["User"])

class userDetailsUpdate(BaseModel):
    username: str | None = None
    email: str | None = None
    password: str| None = None
    

@router.patch("/change-user-details")
async def change_user_details(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    data: userDetailsUpdate = None
):

    
    user = await get_user_from_userid(db, uuid.UUID(user_id))

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.password is None and (data.password is not None or data.email is not None):
        raise HTTPException(status_code=400, detail="User is not registered with google")



    if data.username is not None:
        existing_username = await get_user(db, data.username)
        if existing_username and existing_username.id != user.id:
            raise HTTPException(status_code=400, detail="Username already exists")

    if data.email is not None:
        existing_email = await get_user_by_email(db, data.email)
        if existing_email and existing_email.id != user.id:
            raise HTTPException(status_code=400, detail="Email already exists")    

    # If email or password is being changed, we require OTP
    if data.email is not None or data.password is not None:
        otp_code = str(random.randint(100000, 999999))
        
        # Send OTP to the new email if changing email, otherwise to the current email
        target_email = data.email if data.email is not None else user.email
        
        try:
            await send_otp_email(target_email, otp_code)
        except Exception as e:
            print(f"Failed to send OTP email: {e}")
            raise HTTPException(status_code=500, detail="Failed to send OTP email")
        
        temp_token = uuid.uuid4().hex
        update_data = {
            "user_id": str(user.id),
            "otp": otp_code,
            "new_username": data.username,
            "new_email": data.email,
            "new_password": data.password
        }
        
        await redis_otp_db.setex(f"pending_update:{temp_token}", 300, json.dumps(update_data))
        
        return {"status": "pending_otp", "access_token": temp_token, "message": f"OTP sent to {target_email}"}
    
    # If ONLY username is being changed, apply immediately
    if data.username is not None:
        user.username = data.username
        await db.commit()
        await db.refresh(user)
        return {"message": "User details updated successfully"}

    return {"message": "No changes requested"}

class VerifyUpdateOtp(BaseModel):
    token: str
    otp: str

@router.post("/verify-update")
async def verify_update_otp(
    cred: VerifyUpdateOtp,
    db: AsyncSession = Depends(get_db)
):
    update_data_bytes = await redis_otp_db.get(f"pending_update:{cred.token}")
    if not update_data_bytes:
        raise HTTPException(status_code=400, detail="OTP session expired or invalid. Please request a new OTP.")
    
    update_data = json.loads(update_data_bytes.decode("utf-8"))
    
    if update_data["otp"] != cred.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP code.")
        
    user_id = update_data["user_id"]
    user = await get_user_from_userid(db, uuid.UUID(user_id))
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Apply changes
    if update_data.get("new_username"):
        user.username = update_data["new_username"]
    if update_data.get("new_email"):
        user.email = update_data["new_email"]
    if update_data.get("new_password"):
        user.password = get_password_hash(update_data["new_password"])
        
    await db.commit()
    await db.refresh(user)
    
    await redis_otp_db.delete(f"pending_update:{cred.token}")
    
    return {"message": "User details updated successfully"}
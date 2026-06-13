import os
import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv()

# Assuming you are testing locally. In production, this would be your Cloud Redis URL (like Upstash).
REDIS_OTP_URL = os.getenv("REDIS_OTP_URL", "redis://localhost:6379")
redis_otp_db = redis.from_url(REDIS_OTP_URL)


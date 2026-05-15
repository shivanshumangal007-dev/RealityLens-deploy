import os
import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv()

# Assuming you are testing locally. In production, this would be your Cloud Redis URL (like Upstash).
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_db = redis.from_url(REDIS_URL, decode_responses=True)
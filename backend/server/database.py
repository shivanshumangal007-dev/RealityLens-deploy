import os
import re
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

# 1. Configuration & Engine Setup
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    # Ensures the async driver (+psycopg) is used even if not in .env
    DATABASE_URL = re.sub(r'^postgresql:', 'postgresql+psycopg:', DATABASE_URL)

engine = create_async_engine(
    DATABASE_URL, 
    pool_size=5, 
    max_overflow=10,
    echo=True  # Set to False in production to clean up logs
)

# 2. Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine, 
    expire_on_commit=False,
    class_=AsyncSession
)

# 3. Base Class for Models
class Base(DeclarativeBase):
    pass

# 4. FastAPI Dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

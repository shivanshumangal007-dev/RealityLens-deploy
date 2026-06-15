"""
main.py
───────
Application entry point. Handles:
  - App creation & lifespan (DB migrations, scheduler)
  - CORS middleware
  - Router registration

Business logic lives in routers/ and services/.
"""
from pydantic import BaseModel
import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from .database import AsyncSessionLocal, Base, engine
from .crud import cleanup_stale_jobs
from .models import Job
from .routers import auth, jobs

# ── Scheduled task ────────────────────────────────────────────────────────────

async def delete_old_rows():
    """Delete jobs older than 10 days. Runs at midnight via APScheduler."""
    async with AsyncSessionLocal() as db:
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=10)
            stmt = delete(Job).where(Job.created_at < cutoff_time)
            await db.execute(stmt)
            await db.commit()
            print(f"Deleted jobs older than 10 days at {datetime.now(timezone.utc)}")
        except Exception as e:
            print(f"Error during background deletion: {e}")
            await db.rollback()

# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the nightly cleanup scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(delete_old_rows, "cron", hour=0, minute=0)
    scheduler.start()

    # Run DB migrations
    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()

        from sqlalchemy import text

        migration_queries = [
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR UNIQUE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS password VARCHAR",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR UNIQUE",
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS image_url VARCHAR",
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cloudinary_public_id VARCHAR",
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS time_taken DOUBLE PRECISION",
        ]
        for query in migration_queries:
            try:
                await conn.execute(text(query))
                await conn.commit()
            except Exception as e:
                print(f"Migration error for query '{query}':", e)
                await conn.rollback()

        # Drop leftover NOT NULL constraints from old schema versions
        try:
            known_user_columns = ("id", "created_at", "username", "password", "email")
            not_in_list = ", ".join(f"'{c}'" for c in known_user_columns)
            result = await conn.execute(text(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'users'
                  AND table_schema = 'public'
                  AND is_nullable = 'NO'
                  AND column_name NOT IN ({not_in_list})
            """))
            for row in result.fetchall():
                col = row[0]
                print(f"Migration: dropping NOT NULL on users.{col}")
                await conn.execute(text(f'ALTER TABLE users ALTER COLUMN "{col}" DROP NOT NULL'))

            known_job_columns = ("id", "status", "created_at")
            not_in_list = ", ".join(f"'{c}'" for c in known_job_columns)
            result = await conn.execute(text(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'jobs'
                  AND table_schema = 'public'
                  AND is_nullable = 'NO'
                  AND column_name NOT IN ({not_in_list})
            """))
            for row in result.fetchall():
                col = row[0]
                print(f"Migration: dropping NOT NULL on jobs.{col}")
                await conn.execute(text(f'ALTER TABLE jobs ALTER COLUMN "{col}" DROP NOT NULL'))

            await conn.commit()
        except Exception as e:
            print("Migration error dropping NOT NULL constraints:", e)
            await conn.rollback()

    # Clean up stale jobs from before the last restart
    async with AsyncSessionLocal() as db:
        await cleanup_stale_jobs(db)

    # Run the row cleanup once on startup in case server was offline at midnight
    await delete_old_rows()

    yield

    scheduler.shutdown()

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="RealityLens Backend", lifespan=lifespan)

from starlette.middleware.sessions import SessionMiddleware
import os

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "realitylens-super-secret-key")
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(jobs.router)


@app.get("/health_check")
async def health_check():
    return {"status": "healthy"}

class updateCheck(BaseModel):
    version: str



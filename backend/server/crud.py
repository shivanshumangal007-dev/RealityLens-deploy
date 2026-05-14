from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.sql import case, func
from sqlalchemy.dialects.postgresql import insert
from .models import Job, RateLimit, User
from datetime import datetime, timezone, timedelta
import uuid


RATE_LIMIT_MAX = 30
RATE_LIMIT_WINDOW_HOURS = 1


async def create_job(db: AsyncSession, device_id: str, user_id: uuid.UUID | None) -> Job:

    job = Job(user_id=user_id, device_id=device_id, status="pending")
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job

async def update_job_status(db: AsyncSession, job_id: uuid.UUID, status: dict):
    await db.execute(
        update(Job).where(Job.id == job_id).values(status=status)
    )
    await db.commit()

async def complete_job(db: AsyncSession, job_id: uuid.UUID, result: dict):
    await db.execute(
        update(Job).where(Job.id == job_id).values(
            status="done",
            result=result,
            completed_at=datetime.now(timezone.utc)
        )
    )
    await db.commit()
    await db.close()

async def fail_job(db: AsyncSession, job_id: uuid.UUID, error_message: str):
    await db.execute(
        update(Job).where(Job.id == job_id).values(
            status="failed",
            error=error_message,
            completed_at=datetime.now(timezone.utc)
        )
    )
    await db.commit()
    await db.close()

async def get_job(db: AsyncSession, job_id: uuid.UUID) -> Job | None:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()

async def check_rate_limit(db: AsyncSession, device_id: str) -> bool:
    now = datetime.now(timezone.utc)
    window_cutoff = now - timedelta(hours=RATE_LIMIT_WINDOW_HOURS)

    stmt = (
        insert(RateLimit)
        .values(device_id=device_id, request_count=1, window_start=now)
        .on_conflict_do_update(
            index_elements=["device_id"],
            set_={
                "request_count": case(
                    (RateLimit.window_start < window_cutoff, 1),
                    else_=RateLimit.request_count + 1
                ),
                "window_start": case(
                    (RateLimit.window_start < window_cutoff, now),
                    else_=RateLimit.window_start
                ),
            }
        )
        .returning(RateLimit.request_count)
    )
    result = await db.execute(stmt)
    await db.commit()
    count = result.scalar_one()
    return count <= RATE_LIMIT_MAX


async def cleanup_stale_jobs(db: AsyncSession):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    await db.execute(
        delete(Job).where(Job.created_at < cutoff, Job.status.notin_(["done", "completed", "failed"]))
    )
    await db.commit()


async def get_user_jobs(db: AsyncSession, user_id: uuid.UUID) -> list[Job]:
    result = await db.execute(
        select(Job)
        .where(Job.user_id == user_id)
        .order_by(Job.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()
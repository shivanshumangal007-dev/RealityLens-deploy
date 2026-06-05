from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.sql import case, func
from sqlalchemy.dialects.postgresql import insert
from .models import Job, RateLimit, User
from datetime import datetime, timezone, timedelta
import uuid
import getpass

RATE_LIMIT_MAX = 30
RATE_LIMIT_WINDOW_HOURS = 1


from .auth import get_password_hash

async def create_user(db: AsyncSession, username: str, password: str, email: str) -> User:
    user = User(username=username, password=get_password_hash(password), email=email)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def get_user(db: AsyncSession, name: str) -> User | None:
    result = await db.execute(select(User).where(User.username == name))
    return result.scalar_one_or_none()

async def get_user_from_userid(db:AsyncSession, userid: uuid.UUID) ->User| None:
    result = await db.execute(select(User).where(User.id == userid))
    return result.scalar_one_or_none()

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()



async def create_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    image_url: str | None = None,
    cloudinary_public_id: str | None = None,
) -> Job:
    job = Job(
        user_id=user_id,
        status="pending",
        image_url=image_url,
        cloudinary_public_id=cloudinary_public_id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job

async def update_job_status(db: AsyncSession, job_id: uuid.UUID, status: dict):
    await db.execute(
        update(Job).where(Job.id == job_id).values(status=status)
    )
    await db.commit()

async def complete_job(db: AsyncSession, job_id: uuid.UUID, result: dict, time_taken: float | None = None):
    await db.execute(
        update(Job).where(Job.id == job_id).values(
            status="done",
            result=result,
            completed_at=datetime.now(timezone.utc),
            time_taken=time_taken
        )
    )
    await db.commit()
    await db.close()

async def fail_job(db: AsyncSession, job_id: uuid.UUID, error_message: str, time_taken: float | None = None):
    await db.execute(
        update(Job).where(Job.id == job_id).values(
            status="failed",
            error=error_message,
            completed_at=datetime.now(timezone.utc),
            time_taken=time_taken
        )
    )
    await db.commit()
    await db.close()

async def get_job(db: AsyncSession, job_id: uuid.UUID) -> Job | None:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()

async def check_rate_limit(db: AsyncSession, user_id: uuid.UUID) -> bool:
    now = datetime.now(timezone.utc)
    window_cutoff = now - timedelta(hours=RATE_LIMIT_WINDOW_HOURS)

    stmt = (
        insert(RateLimit)
        .values(user_id=user_id, request_count=1, window_start=now)
        .on_conflict_do_update(
            index_elements=["user_id"],
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

async def delete_old_rows(db: AsyncSession):
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=10)
    
    # Create the deletion query
    stmt = delete(Job).where(Job.created_at < cutoff_time)
    
    # Execute and commit
    await db.execute(stmt)
    await db.commit()

    print(f"Deleted jobs older than 3 days at {datetime.now(timezone.utc)}")


async def get_user_jobs(db: AsyncSession, user_id: uuid.UUID) -> list[Job]:
    result = await db.execute(
        select(Job)
        .where(Job.user_id == user_id)
        .order_by(Job.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()
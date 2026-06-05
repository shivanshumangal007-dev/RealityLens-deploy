"""
routers/jobs.py
───────────────
All job/analysis endpoints:
  POST /submit
  GET  /status/{job_id}
  GET  /result/{job_id}
  GET  /history
"""
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..crud import create_job, get_job
from ..database import get_db
from ..models import Job
from ..services.analysis import rate_limit_using_redis, run_analysis
from .deps import get_current_user_id

router = APIRouter(tags=["Jobs"])

UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/submit")
async def submit_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # Check rate limit first
    allowed = await rate_limit_using_redis(user_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    image_bytes = await file.read()

    job = await create_job(db, user_id=uuid.UUID(user_id))
    file_path = os.path.join(UPLOAD_DIR, f"{job.id}_{file.filename}")

    with open(file_path, "wb") as buffer:
        buffer.write(image_bytes)

    background_tasks.add_task(run_analysis, str(job.id), file_path)
    return {"job_id": str(job.id)}


@router.get("/status/{job_id}")
async def status_endpoint(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    job = await get_job(db, uuid.UUID(job_id))
    if not job or str(job.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": job.status}


@router.get("/result/{job_id}")
async def result_endpoint(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    job = await get_job(db, uuid.UUID(job_id))
    if not job or str(job.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "failed":
        raise HTTPException(status_code=500, detail=job.error)
    if job.status not in ("done", "completed"):
        return Response(status_code=202)

    result_data = job.result
    if isinstance(result_data, dict):
        result_data = {**result_data, "image_url": job.image_url, "time_taken": job.time_taken}
    return result_data


@router.get("/history")
async def history_endpoint(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Job)
        .filter(Job.user_id == uuid.UUID(user_id))
        .order_by(Job.created_at.desc())
    )
    return [
        {
            "id": str(job.id),
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "status": job.status,
            "result": job.result,
            "error": job.error,
            "user_id": str(job.user_id),
            "image_url": job.image_url,
            "time_taken": job.time_taken,
        }
        for job in result.scalars()
    ]

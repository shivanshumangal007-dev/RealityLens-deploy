"""
services/analysis.py
────────────────────
Background processing: AI verification pipeline + Cloudinary upload.
All the heavy-lifting that used to live in main.py lives here.
"""
import asyncio
import io
import os
import time
import uuid

import cloudinary
import cloudinary.uploader
from sqlalchemy import update

from backend.ai_calls import extractCall, searchCall, scoreCall
from ..database import AsyncSessionLocal
from ..crud import update_job_status, complete_job, fail_job
from ..models import Job
from ..redisDatabase import redis_db

# ── Rate limiting ─────────────────────────────────────────────────────────────

async def rate_limit_using_redis(user_id: str) -> bool:
    MAX_REQUESTS = 2
    WINDOW_SECONDS = 60

    redis_key = f"rate_limit:{user_id}"
    current_count = await redis_db.get(redis_key)

    if current_count and int(current_count) >= MAX_REQUESTS:
        return False

    pipe = redis_db.pipeline()
    pipe.incr(redis_key)
    if not current_count:
        pipe.expire(redis_key, WINDOW_SECONDS)
    await pipe.execute()
    return True

# ── AI verification pipeline ──────────────────────────────────────────────────

async def verify_content(image_path: str, on_status=None):
    """Run the three-phase AI pipeline: extract → search → score."""
    start_time = time.time()
    print(f"⏱️ Initiation started at: {time.strftime('%H:%M:%S', time.localtime(start_time))}")

    async def status(msg: str):
        if on_status:
            await on_status(msg)

    # Phase 1: extraction
    ext_start = time.time()
    await status("Extracting information from screenshot...")
    extraction = await extractCall.extractionCall(image_path)
    print(f"⏱️ Extraction time: {time.time() - ext_start:.2f}s")
    print(extraction)

    if isinstance(extraction, str):
        return extraction
    if isinstance(extraction, dict) and extraction.get("error"):
        return extraction
    if "verdict" in extraction:
        return extraction

    # Phase 2: search
    search_start = time.time()
    await status("Searching for relevant information...")
    search_text = await searchCall.searchCall(extraction)
    print(f"⏱️ Searching time: {time.time() - search_start:.2f}s")

    # Phase 3: scoring
    score_start = time.time()
    await status("Scoring and generating verdict...")
    result = await scoreCall.scoreCall(extraction, search_text)
    score_end = time.time()
    print(f"⏱️ Scoring time: {score_end - score_start:.2f}s")
    print(f"⏱️ Total verification time: {score_end - start_time:.2f}s")

    await status("Analysis complete.")
    return result

# ── Status callback factory ───────────────────────────────────────────────────

def make_status_callback(job_id: str):
    """Returns an async callable that writes status updates to the DB."""
    async def callback(message: str):
        try:
            async with AsyncSessionLocal() as db:
                await update_job_status(db, uuid.UUID(job_id), message)
        except Exception as e:
            print(f"Status update failed for {job_id}: {e}")
    return callback

# ── Background analysis task ──────────────────────────────────────────────────

async def run_analysis(job_id: str, file_path: str):
    """Upload image to Cloudinary and run the AI pipeline in parallel."""
    start_time = time.time()
    async with AsyncSessionLocal() as db:
        try:
            loop = asyncio.get_event_loop()

            def do_upload():
                with open(file_path, "rb") as f:
                    image_bytes = f.read()
                image_stream = io.BytesIO(image_bytes)
                return cloudinary.uploader.upload(image_stream, folder="realitylens_uploads")

            upload_task = loop.run_in_executor(None, do_upload)
            analysis_task = verify_content(file_path, make_status_callback(job_id))

            # Run both in parallel
            upload_result, result = await asyncio.gather(upload_task, analysis_task)

            secure_url = upload_result.get("secure_url")
            public_id = upload_result.get("public_id")

            await db.execute(
                update(Job)
                .where(Job.id == uuid.UUID(job_id))
                .values(image_url=secure_url, cloudinary_public_id=public_id)
            )
            await db.commit()

            time_taken = time.time() - start_time
            await complete_job(db, uuid.UUID(job_id), result, time_taken=time_taken)

        except Exception as e:
            print(f"❌ run_analysis failed for job {job_id}: {e}")
            time_taken = time.time() - start_time
            await fail_job(db, uuid.UUID(job_id), str(e), time_taken=time_taken)
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

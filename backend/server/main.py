import os
import shutil

import asyncio
import sys
from datetime import datetime, timezone, timedelta

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from sqlalchemy import select, update, delete

import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from .models import Job
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Header, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.ai_calls import extractCall, searchCall, scoreCall
from .database import get_db, AsyncSessionLocal, engine, Base
from .crud import (
    create_job,
    update_job_status,
    complete_job,
    fail_job,
    get_job,
    check_rate_limit,
    cleanup_stale_jobs,
    delete_old_rows,
)


from fastapi import FastAPI
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler


    
async def delete_old_rows():
    # Use your session maker directly in an async with block
    async with AsyncSessionLocal() as db:
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=10)
            
            # Create the deletion query
            stmt = delete(Job).where(Job.created_at < cutoff_time)
            
            # Execute and commit
            await db.execute(stmt)
            await db.commit()

            # Fixed the print statement to match the 10 days!
            print(f"Deleted jobs older than 10 days at {datetime.now(timezone.utc)}")
            
        except Exception as e:
            # Always good to catch errors in background tasks so they don't crash silently
            print(f"Error during background deletion: {e}")
            await db.rollback()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the scheduler
    scheduler = AsyncIOScheduler()
    
    # 2. Pass the function name WITHOUT calling it. No Depends() allowed here.
    scheduler.add_job(delete_old_rows, 'cron', hour=0, minute=0)
    
    # Start the scheduler
    scheduler.start()
    
    yield
    
    # Shut down the scheduler cleanly when FastAPI stops
    scheduler.shutdown()


app = FastAPI(title="RealityLens Backend")

UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Thread pool for running blocking analysis
executor = ThreadPoolExecutor(max_workers=3)


from .redisDatabase import redis_db

async def rate_limit_using_redis(device_id: str) -> bool:
    MAX_REQUESTS = 5
    WINDOW_SECONDS = 60

    # We create a unique key for this specific user/device
    # Example key: "rate_limit:abc-123-device-id"
    redis_key = f"rate_limit:{device_id}"

    # Get their current request count
    current_count = await redis_db.get(redis_key)

    if current_count and int(current_count) >= MAX_REQUESTS:
        # They hit the limit!
        return False
    
    # If they haven't hit the limit, we use a Redis "pipeline" to do two things at exactly the same time:
    # 1. Increase their count by 1
    # 2. If it's their very first request, start the 60-second self-destruct timer
    pipe = redis_db.pipeline()
    pipe.incr(redis_key)
    
    if not current_count:
        pipe.expire(redis_key, WINDOW_SECONDS)
        
    await pipe.execute()
    return True

# ── Startup ──────────────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Handle simple migrations for newly added columns
        from sqlalchemy import text
        try:
            await conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL"))
        except Exception as e:
            print("Migration error user_id:", e)
        try:
            await conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS username VARCHAR"))
        except Exception as e:
            print("Migration error username:", e)
    async with AsyncSessionLocal() as db:
        await cleanup_stale_jobs(db)





def verify_content(image_path, on_status=None):
    # Phase 1: extraction
    
    def status(msg):
        if on_status:
            on_status(msg)

    status("Extracting information from screenshot...")
    extraction = extractCall.extractionCall(image_path)
    
    print(extraction)
    # extractionCall returns either a dict or an error string/dict
    if isinstance(extraction, str):
        return extraction
    if isinstance(extraction, dict) and extraction.get("error"):
        return extraction
    

    if "verdict" in extraction:
        return extraction
    
    # Phase 2: search
    status("Searching for relevant information...")
    search_text = searchCall.searchCall(extraction)

    # Phase 3: scoring
    status("Scoring and generating verdict...")
    result = scoreCall.scoreCall(extraction, search_text)
    status("Analysis complete.")
    return result

def make_status_callback(job_id: str):
    """Returns a callable that writes status updates to the db synchronously."""
    def callback(message: str):
        async def _update():
            async with AsyncSessionLocal() as db:
                await update_job_status(db, uuid.UUID(job_id), message)


        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_update())
        finally:
            loop.close()
    return callback


async def run_analysis(job_id: str, file_path: str):
    async with AsyncSessionLocal() as db:
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                executor,
                verify_content,
                file_path,
                make_status_callback(job_id),
            )
            await complete_job(db, uuid.UUID(job_id), result)
        except Exception as e:
            print(f"❌ run_analysis failed for job {job_id}: {e}")  # add this
            await fail_job(db, uuid.UUID(job_id), str(e))
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)



@app.post("/submit")
async def submit_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    device_id: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    allowed = await rate_limit_using_redis(device_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    job = await create_job(db, device_id=device_id, user_id=None)
    file_path = os.path.join(UPLOAD_DIR, f"{job.id}_{file.filename}")

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    background_tasks.add_task(run_analysis, str(job.id), file_path)
    return {"job_id": str(job.id)}


@app.get("/status/{job_id}")
async def status_endpoint(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await get_job(db, uuid.UUID(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": job.status}



@app.get("/result/{job_id}")
async def result_endpoint(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await get_job(db, uuid.UUID(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "failed":
        raise HTTPException(status_code=500, detail=job.error)
    if job.status not in ("done", "completed"):
        return Response(status_code=202)
    return job.result


@app.get("/history/{device_id}")
async def history_endpoint(device_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).filter(Job.device_id == device_id).order_by(Job.created_at.desc()))
    history_list = [ {
            "id": str(job.id),
            "created_at": job.created_at,
            "status": job.status,
            "result": job.result,
            "error": job.error,
            "device_id": job.device_id
        } for job in result.scalars() ]
    return history_list


@app.get("/health_check")
async def health_check():
    return {"status": "healthy"}






# from fastapi import WebSocket, WebSocketDisconnect
# from sqlalchemy import select
# import asyncio
# from .models import Job

# @app.websocket("/ws/job/{job_id}")
# async def websocket_endpoint(websocket: WebSocket, job_id: str):
#     await websocket.accept()
#     last_status = None
    
#     try:
#         while True:
#             # Fetch with a fresh session each poll so status/result updates are visible.
#             async with AsyncSessionLocal() as db:
#                 result = await db.execute(select(Job).filter(Job.id == uuid.UUID(job_id)))
#                 job = result.scalar_one_or_none()

#             if not job:
#                 await websocket.send_json({"error": "Job not found"})
#                 break

#             # 2. Only send an update if the status or result actually changed
#             if job.status != last_status or job.status == "done":
#                 payload = {
#                     "status": job.status,
#                     "result": job.result if job.status == "done" else None,
#                     "error": job.error
#                 }
#                 await websocket.send_json(payload)
#                 last_status = job.status

#             # 3. If finished, close the connection
#             if job.status in ["done", "failed", "completed"]:
#                 break

#             # Wait a bit before checking the DB again (Don't spam your own DB!)
#             await asyncio.sleep(1) 

#     except WebSocketDisconnect:
#         print(f"Client disconnected from job {job_id}")
#     except Exception as e:
#         print(f"WS Error: {e}")
#     finally:
#         if websocket.client_state.name != "DISCONNECTED":
#             await websocket.close()






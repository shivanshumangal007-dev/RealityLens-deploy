import os
import shutil

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor

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
)

app = FastAPI(title="RealityLens Backend")

UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Thread pool for running blocking analysis
executor = ThreadPoolExecutor(max_workers=3)


# ── Startup ──────────────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
    allowed = await check_rate_limit(db, device_id)
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


from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
import asyncio
from .models import Job

@app.websocket("/ws/job/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    last_status = None
    
    try:
        while True:
            # Fetch with a fresh session each poll so status/result updates are visible.
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Job).filter(Job.id == uuid.UUID(job_id)))
                job = result.scalar_one_or_none()

            if not job:
                await websocket.send_json({"error": "Job not found"})
                break

            # 2. Only send an update if the status or result actually changed
            if job.status != last_status or job.status == "done":
                payload = {
                    "status": job.status,
                    "result": job.result if job.status == "done" else None,
                    "error": job.error
                }
                await websocket.send_json(payload)
                last_status = job.status

            # 3. If finished, close the connection
            if job.status in ["done", "failed", "completed"]:
                break

            # Wait a bit before checking the DB again (Don't spam your own DB!)
            await asyncio.sleep(1) 

    except WebSocketDisconnect:
        print(f"Client disconnected from job {job_id}")
    except Exception as e:
        print(f"WS Error: {e}")
    finally:
        if websocket.client_state.name != "DISCONNECTED":
            await websocket.close()




@app.get("/health_check")
async def health_check():
    return {"status": "healthy"}

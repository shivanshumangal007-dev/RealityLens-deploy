import os
import shutil

import asyncio
import sys
from datetime import datetime, timezone, timedelta
import cloudinary
import cloudinary.uploader
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from sqlalchemy import select, update, delete

import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from .models import Job
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Header, Depends, Response, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from .auth import verify_password, create_access_token, ALGORITHM, SECRET_KEY
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
    create_user,
    get_user,
)
from pydantic import BaseModel


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
    
    # Pass the function name WITHOUT calling it
    scheduler.add_job(delete_old_rows, 'cron', hour=0, minute=0)
    
    # Start the scheduler
    scheduler.start()
    
    # Run Database Migrations
    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()
        
        # Handle simple migrations for newly added columns safely
        from sqlalchemy import text
        
        migration_queries = [
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR UNIQUE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS password VARCHAR",
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS image_url VARCHAR",
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cloudinary_public_id VARCHAR"
        ]
        
        for query in migration_queries:
            try:
                await conn.execute(text(query))
                await conn.commit()
            except Exception as e:
                print(f"Migration error for query '{query}':", e)
                await conn.rollback()
        
        # Drop NOT NULL on any leftover columns from old schema versions for both tables
        try:
            # Users table
            known_user_columns = ("id", "created_at", "username", "password")
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
                
            # Jobs table
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
            
    # Cleanup stale jobs
    async with AsyncSessionLocal() as db:
        await cleanup_stale_jobs(db)
        
    yield
    
    # Shut down the scheduler cleanly when FastAPI stops
    scheduler.shutdown()

app = FastAPI(title="RealityLens Backend", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware
origins = [
    "http://localhost:3000", # Dev URL
    "http://127.0.0.1:3000",
    "localhost:5173"
    # "*" can be used if your API is strictly local and not exposed to the web
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Or specify the exact list above
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#this is where the captured_img is stored
UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Thread pool for running blocking analysis
executor = ThreadPoolExecutor(max_workers=3)


#this is where we use redis to check if the device id is valid
from .redisDatabase import redis_db


async def rate_limit_using_redis(user_id: str) -> bool:
    MAX_REQUESTS = 60
    WINDOW_SECONDS = 60

    # We create a unique key for this specific user/device
    # Example key: "rate_limit:abc-123-device-id"
    redis_key = f"rate_limit:{user_id}"

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
# Startup logic is now handled in the lifespan manager.
# the main function for verification 
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


# changing the status in the database for a job after the analysis
def make_status_callback(job_id: str):
    """Returns a callable that writes status updates to the db synchronously."""

    def callback(message: str):
        async def _update():
            async with AsyncSessionLocal() as db:
                await update_job_status(db, uuid.UUID(job_id), message)

        # we need to create a new event loop because we are not in an async function
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_update())
        finally:
            loop.close()
    return callback

# this is the function that runs the verify_content function
async def run_analysis(job_id: str, file_path: str):
    async with AsyncSessionLocal() as db:
        try:
            loop = asyncio.get_event_loop()
            # run_in_executor runs the function in a separate thread, this thread runs the verify_content
            result = await loop.run_in_executor(
                executor,
                verify_content,
                file_path,
                make_status_callback(job_id),
            )
            #this basically makes the changes in the database
            await complete_job(db, uuid.UUID(job_id), result)
        except Exception as e:
            print(f"❌ run_analysis failed for job {job_id}: {e}")  # add this
            await fail_job(db, uuid.UUID(job_id), str(e))
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

async def get_current_user_id(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    return user_id

# the api for submittimg the image
@app.post("/submit")
async def submit_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    #first check if the device id is valid
    allowed = await rate_limit_using_redis(user_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    #then save the job in the database    
    import io

    image_bytes = await file.read()
    image_stream = io.BytesIO(image_bytes)
    upload_result = cloudinary.uploader.upload(image_stream, folder="realitylens_uploads")   

    secure_url = upload_result.get("secure_url")
    public_id = upload_result.get("public_id")

    job = await create_job(db, user_id=uuid.UUID(user_id), image_url=secure_url, cloudinary_public_id=public_id)
    file_path = os.path.join(UPLOAD_DIR, f"{job.id}_{file.filename}")

    #saving the image 
    with open(file_path, "wb") as buffer:
        buffer.write(image_bytes)
    #this is a background task, meaning it runs in the background and does not block the main thread
    background_tasks.add_task(run_analysis, str(job.id), file_path)
    #this is what we get when we submit the image
    return {"job_id": str(job.id)}

# this is a simple api to get the status of a job
@app.get("/status/{job_id}")
async def status_endpoint(job_id: str, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    #get the job from the database
    job = await get_job(db, uuid.UUID(job_id))
    if not job or str(job.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    #return the status of the job
    return {"status": job.status}

#this is an api to get the result of a job
@app.get("/result/{job_id}")
async def result_endpoint(job_id: str, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    #get the job from the database
    job = await get_job(db, uuid.UUID(job_id))
    #if the job is not found
    if not job or str(job.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "failed":
        raise HTTPException(status_code=500, detail=job.error)
    if job.status not in ("done", "completed"):
        return Response(status_code=202)
    
    result_data = job.result
    if isinstance(result_data, dict):
        result_data = {**result_data, "image_url": job.image_url}
    return result_data

#this is an api to get the history of a job
@app.get("/history")
async def history_endpoint(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    #get the job from the database
    result = await db.execute(select(Job).filter(Job.user_id == uuid.UUID(user_id)).order_by(Job.created_at.desc()))
    #return the history of the job
    history_list = [ {
            "id": str(job.id),
            "created_at": job.created_at,
            "status": job.status,
            "result": job.result,
            "error": job.error,
            "user_id": str(job.user_id),
            "image_url": job.image_url,
        } for job in result.scalars() ]
    return history_list


@app.get("/health_check")
async def health_check():
    return {"status": "healthy"}


class UserCredentials(BaseModel):
    username: str
    password: str

@app.post("/register")
async def register_user(credentials: UserCredentials, db: AsyncSession = Depends(get_db)):
    user = await get_user(db, credentials.username)
    if user:
        raise HTTPException(status_code=400, detail="Username already exists")
    user = await create_user(db, credentials.username, credentials.password)
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer", "user_id": str(user.id)}

@app.post("/login")
async def login_user(credentials: UserCredentials, db: AsyncSession = Depends(get_db)):
    user = await get_user(db, credentials.username)
    if not user or not verify_password(credentials.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer", "user_id": str(user.id)}



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
import os
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
import asyncio
from concurrent.futures import ThreadPoolExecutor
from backend.ai_calls import extractCall, searchCall, scoreCall


current_situation = "Please wait while we analyze the capture..."

def _set_current_situation(message, on_status=None):
    global current_situation
    current_situation = message
    if on_status:
        on_status(message)


def verify_content(image_path, on_status=None):
    """Orchestrate extraction, searching and scoring for an uploaded image.

    Args:
        image_path (str): path to the uploaded image file
    Returns:
        dict or str: scoring result dict or error message
    """
    # Phase 1: extraction
    _set_current_situation("Extracting information from screenshot...", on_status)
    extraction = extractCall.extractionCall(image_path)
    
    print(extraction)
    print("hello")
    # extractionCall returns either a dict or an error string/dict
    if isinstance(extraction, str):
        return extraction
    if isinstance(extraction, dict) and extraction.get("error"):
        return extraction
    

    if "verdict" in extraction:
        return extraction
    
    # Phase 2: search
    _set_current_situation("Searching for relevant information...", on_status)
    search_text = searchCall.searchCall(extraction)

    # Phase 3: scoring
    _set_current_situation("Scoring and generating verdict...", on_status)
    result = scoreCall.scoreCall(extraction, search_text)
    _set_current_situation("Analysis complete.", on_status)
    return result


app = FastAPI(title="RealityLens Backend")

UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Thread pool for running blocking analysis
executor = ThreadPoolExecutor(max_workers=3)

@app.get("/status")
async def status_endpoint():
    """Return the current analysis status."""
    return {"current_situation": current_situation}


@app.post("/ai_client")
async def ai_client_endpoint(file: UploadFile = File(...)):
    # 1. Create a safe path for the uploaded file
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    try:
        # 2. Efficiently save the file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 3. Run verify_content in thread pool to keep it async
        # This allows the /status endpoint to be polled while analysis runs
        global executor 
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            executor,
            verify_content,
            file_path,
            _set_current_situation,
        )

        return result

    except Exception as e:
        # Log the error for debugging
        print(f"❌ Server Error: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
    
    finally:
        # 4. Cleanup: Always remove the file after the response is sent
        if os.path.exists(file_path):
            os.remove(file_path)

@app.get("/health_check")
async def health_check():
    return {"status": "healthy"}

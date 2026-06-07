import io
import json
import random
from google.genai import types
from PIL import Image
from . import getKeys
from . import aiCalls
from ..prompts import extractionPrompt

#function to extract the relevant information from given image
async def extractionCall(image_path):

    #resizing image
    try:
        with Image.open(image_path) as img:
            if img.width > 1280 or img.height > 1280:
                img.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            img = img.convert("RGB")
            
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format="JPEG", quality=85)
            img_bytes = img_byte_arr.getvalue()
            print(f"📦 Image size: {len(img_bytes) / 1024:.1f} KB")

    except Exception as e:
        return f"RealityLens: Failed to read image — {e}"

    image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
    keys_to_try = getKeys.gemini_api_keys[:]
    random.shuffle(keys_to_try)

    # ── Phase 1: Extract claim from screenshot ───────────────────────────────
    #calling groq or gemini vision
    print("🔍 Phase 1: Extracting claim from screenshot...")
    raw_extraction, err = await aiCalls.call_groq_vision(extractionPrompt.EXTRACTION_PROMPT, img_bytes)
    #if groq fails, try gemini vision but gemini is trash so pray that groq works
    if err:
        print(f"⚠️ Groq failed ({err}), trying Gemini vision...")
        raw_extraction, err = await aiCalls.call_gemini(extractionPrompt.EXTRACTION_PROMPT, image_part, keys_to_try=keys_to_try)
        if err:
            return f"RealityLens: Extraction failed — {err}"
    #parsing the response
    try:
        extraction = json.loads(raw_extraction)
    except json.JSONDecodeError:
        return {"error": "Failed to parse extraction response", "raw": raw_extraction}

    claim = extraction.get("claim", "")

    if extraction.get("is_satire"):
        return {
            "claim": claim,
            "reality_score": 0.00,
            "confidence": 0.95,
            "verdict": "SATIRE",
            "explanation": "This content appears to be from a satire or parody account. The claim should not be taken as factual news.",
            "evidence": []
        }

    if claim == "UNREADABLE" or not claim:
        return {
            "claim": "Unable to extract a claim.",
            "reality_score": 0.00,
            "confidence": 0.1,
            "verdict": "UNREADABLE",
            "explanation": "The screenshot was too blurry, cropped, or unclear to extract a verifiable claim.",
            "evidence": []
        }
    
    return extraction
    
async def extractionCallText(text: str):
    keys_to_try = getKeys.gemini_api_keys[:]
    random.shuffle(keys_to_try)

    print("🔍 Phase 1: Extracting claim from text...")
    prompt = f"{extractionPrompt.EXTRACTION_TEXT_PROMPT}\n\nUser Text:\n{text}"
    
    raw_extraction, err = await aiCalls.call_groq_extraction(prompt)
    if err:
        print(f"⚠️ Groq text failed ({err}), trying Gemini...")
        raw_extraction, err = await aiCalls.call_gemini(prompt, keys_to_try=keys_to_try)
        if err:
            return f"RealityLens: Extraction failed — {err}"
            
    try:
        extraction = json.loads(raw_extraction)
    except json.JSONDecodeError:
        return {"error": "Failed to parse extraction response", "raw": raw_extraction}

    claim = extraction.get("claim", "")

    if extraction.get("is_satire"):
        return {
            "claim": claim,
            "reality_score": 0.00,
            "confidence": 0.95,
            "verdict": "SATIRE",
            "explanation": "This content appears to be from a satire or parody account. The claim should not be taken as factual news.",
            "evidence": []
        }

    if claim == "UNREADABLE" or not claim:
        return {
            "claim": "Unable to extract a claim.",
            "reality_score": 0.00,
            "confidence": 0.1,
            "verdict": "UNREADABLE",
            "explanation": "The text was unclear or didn't contain a verifiable claim.",
            "evidence": []
        }
    
    return extraction

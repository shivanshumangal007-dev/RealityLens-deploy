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

    # ── Phase 1: OCR Extraction ───────────────────────────────
    print("🔍 Phase 1: Performing fast OCR on screenshot...")
    try:
        import pytesseract
        import shutil
        import os
        
        # On Windows, set tesseract_cmd to the default install path if it exists
        tess_cmd = os.getenv("TESSERACT_CMD")
        if tess_cmd and os.path.exists(tess_cmd):
            pytesseract.pytesseract.tesseract_cmd = tess_cmd
        elif os.name == 'nt' and os.path.exists(r'C:\Program Files\Tesseract-OCR\tesseract.exe'):
            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        elif not shutil.which("tesseract") and os.name != 'nt':
            return {"error": "RealityLens: Tesseract OCR is not installed. Please install it on the server."}
        elif os.name == 'nt' and not shutil.which("tesseract"):
             return {"error": "RealityLens: Tesseract OCR is not installed. Please download and install Tesseract for Windows."}

        # We already have the PIL image open in the try block above, but it was saved to bytes.
        # Let's just open the image again from the bytes so we don't have to rewrite the image resizing logic above.
        img_for_ocr = Image.open(io.BytesIO(img_bytes))
        extracted_text = pytesseract.image_to_string(img_for_ocr, lang='eng+ara+hin+chi_sim+chi_tra')
            
        print(f"📝 OCR extracted {len(extracted_text)} characters.")
        if len(extracted_text.strip()) < 5:
            return {
                "claim": "Unable to extract a claim.",
                "reality_score": 0.00,
                "confidence": 0.1,
                "verdict": "UNREADABLE",
                "explanation": "The screenshot was too blurry, empty, or unclear for OCR to extract any text.",
                "evidence": []
            }
            
        # Delegate to text-based extraction
        return await extractionCallText(extracted_text)
        
    except ImportError:
        return {"error": "RealityLens: pytesseract module is not installed."}
    except Exception as e:
        return {"error": f"RealityLens: OCR Extraction failed — {e}"}
    
async def extractionCallText(text: str):
    keys_to_try = getKeys.gemini_api_keys[:]
    random.shuffle(keys_to_try)

    print("🔍 Phase 1: Extracting claim from text...")
    prompt = f"{extractionPrompt.EXTRACTION_TEXT_PROMPT}\n\nUser Text:\n{text}"
    
    raw_extraction, err = await aiCalls.call_groq_extraction(prompt)
    
    extraction = None
    if not err:
        try:
            extraction = json.loads(raw_extraction)
        except json.JSONDecodeError:
            print("⚠️ Groq returned invalid JSON, falling back to Gemini...")
            err = "Invalid JSON returned"

    if err:
        print(f"⚠️ Groq text failed ({err}), trying Gemini...")
        raw_extraction, err = await aiCalls.call_gemini(prompt, keys_to_try=keys_to_try)
        if err:
            return f"RealityLens: Extraction failed — {err}"
            
        try:
            extraction = json.loads(raw_extraction)
        except json.JSONDecodeError:
            return {"error": "Failed to parse extraction response from both AI models", "raw": raw_extraction}

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

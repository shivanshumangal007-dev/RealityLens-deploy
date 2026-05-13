from ..prompts import scorePrompt
from . import aiCalls
import json
import re


def _extract_json_payload(raw_text):
    if isinstance(raw_text, (dict, list)):
        return raw_text
    if not isinstance(raw_text, str):
        return None

    text = raw_text.strip()
    if not text:
        return None

    # Fast path: already valid JSON text.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Common LLM format: prose with a fenced JSON block.
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Fallback: find the first decodable JSON value in the text.
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            return obj
        except json.JSONDecodeError:
            continue

    return None


def scoreCall(extraction, search_text):
    """Generate scoring prompt from extraction and search text, call the
    scoring model, and return parsed JSON result.

    Args:
        extraction (dict): extraction result from extractionCall
        search_text (str): formatted search results
    Returns:
        dict: parsed scoring verdict or error dict
    """
    print("🧠 Phase 3: Scoring and generating verdict...")
    scoring_prompt = scorePrompt.build_scoring_prompt(extraction, search_text)
    raw_verdict, err = aiCalls.call_groq(scoring_prompt)
    if err:
        print(f"⚠️ Groq failed ({err}), falling back to Gemini for scoring...")
        raw_verdict, err = aiCalls.call_gemini(scoring_prompt)
        if err:
            return f"RealityLens: Scoring failed — {err}"

    result = _extract_json_payload(raw_verdict)
    if result is not None:
        return result

    print("❌ JSON Parse Error:", raw_verdict)
    return {"error": "AI failed to return valid JSON", "raw": raw_verdict}
from ..prompts import scorePrompt
from . import aiCalls
import json


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

    try:
        result = json.loads(raw_verdict)
        print(result)
        return result
    except json.JSONDecodeError:
        print("❌ JSON Parse Error:", raw_verdict)
        return {"error": "AI failed to return valid JSON", "raw": raw_verdict}
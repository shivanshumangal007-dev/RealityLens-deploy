import os
import time
import requests
import os
import random
from groq import Groq
from tavily import TavilyClient
import base64
import backend.ai_calls.getKeys as getKeys


def call_groq_vision(prompt, image_bytes):
    """Groq vision fallback for extraction when Gemini fails."""
    if not getKeys.groq_api_key:
        return None, "GROQ_API_KEY is missing."

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    groq_client = Groq(api_key=getKeys.groq_api_key)

    # Only these Groq models support vision
    vision_models = getKeys.vision_models

    for model in vision_models:
        try:
            print(f"🔍 Extracting with Groq vision {model}...")
            response = groq_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
                temperature=0.1,
                max_tokens=1500,
            )

            raw = response.choices[0].message.content.strip()
            if raw.startswith("```json"):
                raw = raw.replace("```json", "", 1).replace("```", "", 1).strip()
            elif raw.startswith("```"):
                raw = raw.replace("```", "", 2).strip()

            return raw, None

        except Exception as e:
            err = str(e)
            print(f"⚠️ Groq vision error on {model}: {err}")
            continue

    return None, "All Groq vision models failed."

def call_gemini(prompt, image_part=None, gemini_api_keys=getKeys.gemini_api_keys, keys_to_try=None):
    """Try each key and model until one works. Returns parsed text or raises."""
    if keys_to_try is None:
        keys_to_try = gemini_api_keys[:]
        random.shuffle(keys_to_try)

    MAX_RETRIES = 2
    MAX_TOTAL_SECONDS = 45
    start_time = time.time()
    last_error = "All API keys exhausted."

    i = 0
    while i < len(keys_to_try):
        key = keys_to_try[i]
        key_exhausted = False
        
        for model in getKeys.MODELS:
            for attempt in range(MAX_RETRIES):
                if time.time() - start_time > MAX_TOTAL_SECONDS:
                    return None, "Service timeout. Please try again."

                try:
                    client = getKeys.get_gemini_client(key)
                    contents = [prompt, image_part] if image_part else [prompt]

                    response = client.models.generate_content(
                        model=model,
                        contents=contents,
                    )

                    if not response or not getattr(response, "text", None):
                        last_error = "Empty response from AI."
                        break

                    raw = response.text.strip()
                    if raw.startswith("```json"):
                        raw = raw.replace("```json", "", 1).replace("```", "", 1).strip()
                    elif raw.startswith("```"):
                        raw = raw.replace("```", "", 2).strip()

                    return raw, None

                except Exception as e:
                    err = str(e)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        print(f"⚠️ Quota exhausted on {model}, removing key and trying next...")
                        last_error = "Quota exhausted."
                        # Mark key as exhausted and remove it so subsequent calls skip it
                        keys_to_try.pop(i)
                        key_exhausted = True
                        break
                    elif "503" in err or "UNAVAILABLE" in err:
                        if attempt < MAX_RETRIES - 1:
                            wait = 5 * (attempt + 1)
                            print(f"⚠️ {model} overloaded, retrying in {wait}s...")
                            time.sleep(wait)
                        else:
                            print(f"⚠️ {model} still failing, next model...")
                            last_error = f"{model} unavailable."
                            break
                    else:
                        print(f"⚠️ Error on {model}: {err}")
                        last_error = f"AI Error: {err}"
                        break
            
            if key_exhausted:
                break  # Exit model loop, don't increment i
        
        if not key_exhausted:
            i += 1  # Only increment if key was not exhausted

    return None, last_error

def call_kimi(prompt, image_bytes=None):

    ACCOUNT_ID = os.getenv("ACCOUNT_ID", "").strip()
    AUTH_TOKEN = os.getenv("CLOUDFLARE_AUTH_TOKEN", "").strip()
    
    # Note: image_bytes should be the raw bytes from img_bytes in verify_content
    
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/moonshotai/kimi-k2.5"
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}

    # Construct the content list
    content = [{"type": "text", "text": prompt}]
    
    if image_bytes:
        # Encode bytes to base64 string
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
        })

    try:
        response = requests.post(
            url,
            headers=headers,
            json={"messages": [{"role": "user", "content": content}]}
        )
        
        # Check for Cloudflare success
        res_json = response.json()
        if not res_json.get("success"):
            return None, f"Cloudflare Error: {res_json.get('errors')}"
            
        raw = res_json["result"]["response"].strip()
        
        # Clean up Markdown formatting if present
        if raw.startswith("```json"):
            raw = raw.replace("```json", "", 1).replace("```", "", 1).strip()
        elif raw.startswith("```"):
            raw = raw.replace("```", "", 2).strip()

        return raw, None

    except Exception as e:
        return None, f"Kimi-K2 Connection Error: {str(e)}"
    
def call_groq(prompt):
    """Call Groq API with the given prompt. Returns response text or raises."""
    if not getKeys.groq_api_key:
        raise ValueError("GROQ_API_KEY is missing.")
    

    client = Groq(api_key=getKeys.groq_api_key)
    for model in getKeys.GROQ_MODELS:
        try:
            print(f"🤖 Scoring with Groq {model}...")
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,  # Low temp for consistent structured output
                max_tokens=1500,
            )

            raw = response.choices[0].message.content.strip()
            if raw.startswith("```json"):
                raw = raw.replace("```json", "", 1).replace("```", "", 1).strip()
            elif raw.startswith("```"):
                raw = raw.replace("```", "", 2).strip()

            return raw, None

        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                print(f"⚠️ Groq rate limit on {model}, trying next...")
                continue
            else:
                print(f"⚠️ Groq error on {model}: {err}")
                continue

    return None, "All Groq models failed."

def tavily_search(query, num_results=5):
    """Search using Tavily API. Returns list of result dicts."""
    if not getKeys.tavily_api_key:
        print("⚠️ No Tavily API key found, skipping search.")
        return []

    try:
        client = TavilyClient(api_key=getKeys.tavily_api_key)

        response = client.search(
            query=query,
            max_results=num_results,
            search_depth="basic",  # use "advanced" for better results but costs 2 credits
            include_answer=True,   # Tavily gives a pre-summarized answer too
        )   

        results = []

        # Tavily gives a direct answer summary — prepend it as a result
        if response.get("answer"):
            results.append({
                "title": "Tavily Summary",
                "url": "",
                "description": response["answer"],
                "source": "Tavily AI Summary",
            })

        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("content", ""),
                "source": item.get("url", "").split("/")[2] if item.get("url") else "Unknown",
            })

        return results

    except Exception as e:
        print(f"⚠️ Tavily search failed: {e}")
        return []

def parallel_search(query, num_results=5):
    parallel_key = os.getenv("PARALLEL_API_KEY", "").strip()
    if not parallel_key:
        print("⚠️ No Parallel API key found, skipping search.")
        return []

    try:
        response = requests.post(
            "https://api.parallel.ai/v1beta/search",
            headers={
                "Content-Type": "application/json",
                "x-api-key": parallel_key,
            },
            json={
                "objective": f"Find credible news sources that confirm or deny this claim: {query}",
                "search_queries": [query],
                "mode": "fast",        # fast = <5s, quality = better but slower
                "max_results": num_results,
                "excerpts": {
                    "max_chars_per_result": 1500  # enough context for scoring
                }
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("results", []):
            domain = item.get("url", "").split("/")[2] if item.get("url") else "Unknown"
            excerpts = item.get("excerpts", [])
            description = " ".join(excerpts) if excerpts else ""
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": description,
                "source": domain,
                "publish_date": item.get("publish_date", ""),
            })

        return results

    except Exception as e:
        print(f"⚠️ Parallel search failed: {e}")
        return []
    
def format_search_results(results):
    if not results:
        return "No search results found."

    lines = []
    for i, r in enumerate(results, 1):
        date = f" ({r.get('publish_date', 'date unknown')})" if r.get('publish_date') else ""
        lines.append(f"{i}. {r['source']}{date}: {r['title']}")
        lines.append(f"   URL: {r['url']}")
        lines.append(f"   Summary: {r['description']}")
        lines.append("")
    return "\n".join(lines)
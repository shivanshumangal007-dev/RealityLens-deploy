from backend.prompts.scorePrompt import SCORING_SYSTEM_PROMPT
import os
import time
import os
import random
from groq import AsyncGroq
from tavily import AsyncTavilyClient
import httpx
import asyncio
import base64
import re
import backend.ai_calls.getKeys as getKeys


# function to call groq vision ai
async def call_groq_vision(prompt, image_bytes, groq_api_keys=getKeys.groq_api_keys, keys_to_try=None):
    """Groq vision fallback for extraction when Gemini fails."""
    # check if the groq api key is present
    if not groq_api_keys:
        return None, "GROQ_API_KEY is missing."
        
    if keys_to_try is None:
        keys_to_try = groq_api_keys[:]
        random.shuffle(keys_to_try)
        
    # encode image bytes to base64
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    # only these Groq models support vision
    vision_models = getKeys.vision_models
    
    i = 0
    while i < len(keys_to_try):
        key = keys_to_try[i]
        key_exhausted = False
        # create a groq client
        groq_client = AsyncGroq(api_key=key)
        
        # loop through vision models and try to extract information
        for model in vision_models:
            # try to extract information
            try:
                is_openrouter = "google/" in model or "openrouter" in model.lower()
                current_client = groq_client
                if is_openrouter:
                    print(f"🔄 Routing {model} to OpenRouter...")
                    or_keys = getattr(getKeys, "openrouter_api_keys", [])
                    if not or_keys:
                        print("⚠️ No OpenRouter API key found.")
                        continue
                    or_key = random.choice(or_keys)
                    current_client = AsyncGroq(api_key=or_key, base_url="https://openrouter.ai/api/v1")
                else:
                    print(f"🔍 Extracting with Groq vision {model}...")

                # send the prompt and image to the vision api
                call_start = time.time()
                response = await current_client.chat.completions.create(
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
                    max_tokens=4000,
                )
                print(f"⏱️ {model} responded in {time.time() - call_start:.2f}s")
                # get the raw response
                raw = response.choices[0].message.content.strip()
                # Remove think blocks if present
                raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
                
                # Try to extract from markdown blocks
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
                if json_match:
                    raw = json_match.group(1).strip()
                else:
                    # Fallback to finding first { and last }
                    start_idx = raw.find('{')
                    end_idx = raw.rfind('}')
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        raw = raw[start_idx:end_idx+1].strip()

                return raw, None

            except Exception as e:
                err = str(e)
                if "429" in err or "rate_limit" in err.lower() or "rate limit" in err.lower():
                    print(f"⚠️ Groq rate limit on {model}, trying next key...")
                    keys_to_try.pop(i)
                    key_exhausted = True
                    break
                else:
                    print(f"⚠️ Groq vision error on {model}: {err}")
                    continue
        
        if not key_exhausted:
            i += 1

    return None, "All Groq vision models and keys failed."

async def call_groq_extraction(prompt, groq_api_keys=getKeys.groq_api_keys, keys_to_try=None):
    """Groq fallback for text extraction."""
    if not groq_api_keys:
        return None, "GROQ_API_KEY is missing."

    if keys_to_try is None:
        keys_to_try = groq_api_keys[:]
        random.shuffle(keys_to_try)

    # We can use the regular GROQ_MODELS since we don't need vision
    models = getattr(getKeys, "GROQ_MODELS", ["llama3-70b-8192", "mixtral-8x7b-32768", "llama3-8b-8192"])
    
    i = 0
    while i < len(keys_to_try):
        key = keys_to_try[i]
        key_exhausted = False
        groq_client = AsyncGroq(api_key=key)

        for model in models:
            try:
                is_openrouter = "google/" in model or "openrouter" in model.lower()
                current_client = groq_client
                if is_openrouter:
                    print(f"🔄 Routing {model} to OpenRouter...")
                    or_keys = getattr(getKeys, "openrouter_api_keys", [])
                    if not or_keys:
                        print("⚠️ No OpenRouter API key found.")
                        continue
                    or_key = random.choice(or_keys)
                    current_client = AsyncGroq(api_key=or_key, base_url="https://openrouter.ai/api/v1")
                else:
                    print(f"🔍 Extracting with Groq text {model}...")

                response = await current_client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": prompt
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
                if "429" in err or "rate limit" in err.lower() or "rate_limit" in err.lower():
                    print(f"⚠️ Groq rate limit on {model}, trying next key...")
                    keys_to_try.pop(i)
                    key_exhausted = True
                    break
                else:
                    print(f"⚠️ Groq text error on {model}: {err}")
                    continue

        if not key_exhausted:
            i += 1

    return None, "All Groq text models and keys failed."

# function to call gemini ai
async def call_gemini(prompt, image_part=None, gemini_api_keys=getKeys.gemini_api_keys, keys_to_try=None):
    """Try each key and model until one works. Returns parsed text or raises."""
    
    # if keys_to_try is None:
    if keys_to_try is None:
        # copy the gemini api keys and shuffle them
        keys_to_try = gemini_api_keys[:]
        random.shuffle(keys_to_try)
    # set max retries and max total seconds this is added because i noticed that sometimes gemini shows high traffic try again later
    MAX_RETRIES = 2
    MAX_TOTAL_SECONDS = 45
    start_time = time.time()
    last_error = "All API keys exhausted."
    # loop through the keys
    i = 0
    while i < len(keys_to_try):
        # get the current key i have specially made the keys to be randamized because it would first loop through all the exhausted ones first taking more time 
        key = keys_to_try[i]
        key_exhausted = False
        # loop through the models
        for model in getKeys.GEMINI_MODELS:
            # loop through the retries
            for attempt in range(MAX_RETRIES):
                # check if the time limit is reached
                if time.time() - start_time > MAX_TOTAL_SECONDS:
                    return None, "Service timeout. Please try again."
                try:
                    client = getKeys.get_gemini_client(key)
                    # create the contents
                    contents = [prompt, image_part] if image_part else [prompt]
                    # send the prompt and image to the gemini ai
                    call_start = time.time()
                    response = await client.aio.models.generate_content(
                        model=model,
                        contents=contents,
                    )
                    print(f"⏱️ Gemini {model} responded in {time.time() - call_start:.2f}s")
                    # check if the response is empty
                    if not response or not getattr(response, "text", None):
                        last_error = "Empty response from AI."
                        break
                    # clean up the response
                    raw = response.text.strip()
                    # remove markdown code blocks if present
                    if raw.startswith("```json"):
                        raw = raw.replace("```json", "", 1).replace("```", "", 1).strip()
                    elif raw.startswith("```"):
                        raw = raw.replace("```", "", 2).strip()
                    # return the response
                    return raw, None

                except Exception as e:
                    err = str(e)
                    # handle 429 and RESOURCE_EXHAUSTED errors
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        print(f"⚠️ Quota exhausted on {model}, removing key and trying next...")
                        last_error = "Quota exhausted."
                        # Mark key as exhausted and remove it so subsequent calls skip it
                        keys_to_try.pop(i)
                        key_exhausted = True
                        break
                    elif "503" in err or "UNAVAILABLE" in err: 
                        # handle 503 and UNAVAILABLE errors when model is overloaded
                        if attempt < MAX_RETRIES - 1:
                            wait = 5 * (attempt + 1)
                            print(f"⚠️ {model} overloaded, retrying in {wait}s...")
                            await asyncio.sleep(wait)
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

async def call_kimi(prompt, image_bytes=None):

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
        async with httpx.AsyncClient() as client:
            response = await client.post(
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
    
async def call_groq(prompt, groq_api_keys=getKeys.groq_api_keys, keys_to_try=None):
    """Call Groq API with the given prompt. Returns response text or raises."""
    if not groq_api_keys:
        raise ValueError("GROQ_API_KEY is missing.")
    
    if keys_to_try is None:
        keys_to_try = groq_api_keys[:]
        random.shuffle(keys_to_try)

    MAX_RETRIES = 2
    i = 0
    while i < len(keys_to_try):
        key = keys_to_try[i]
        key_exhausted = False
        client = AsyncGroq(api_key=key)

        for model in getKeys.GROQ_MODELS:
            for attempt in range(MAX_RETRIES):
                try:
                    is_openrouter = "google/" in model or "openrouter" in model.lower()
                    current_client = client
                    if is_openrouter:
                        or_keys = getattr(getKeys, "openrouter_api_keys", [])
                        if not or_keys:
                            print("⚠️ No OpenRouter API key found.")
                            break
                        or_key = random.choice(or_keys)
                        current_client = AsyncGroq(api_key=or_key, base_url="https://openrouter.ai/api/v1")
                        print(f"🔄 Scoring with OpenRouter {model}...")
                    else:
                        print(f"🤖 Scoring with Groq {model}...")

                    response = await current_client.chat.completions.create(
                        model=model,
                            messages=[
                                {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                                {"role": "user", "content": prompt}
                            ],
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
                    if "429" in err or "rate_limit" in err.lower() or "rate limit" in err.lower():
                        if attempt < MAX_RETRIES - 1:
                            wait = 5 * (attempt + 1)
                            print(f"⚠️ Groq rate limit on {model}, retrying in {wait}s...")
                            await asyncio.sleep(wait)
                            continue
                        else:
                            print(f"⚠️ Groq rate limit on {model} persists, trying next key...")
                            keys_to_try.pop(i)
                            key_exhausted = True
                            break
                    else:
                        print(f"⚠️ Groq error on {model}: {err}")
                        break 
            
            if key_exhausted:
                break

        if not key_exhausted:
            i += 1

    return None, "All Groq models and keys failed."

async def tavily_search(query, num_results=5, tavily_api_keys=getKeys.tavily_api_keys, keys_to_try=None):
    """Search using Tavily API. Returns list of result dicts."""
    if not tavily_api_keys:
        print("⚠️ No Tavily API key found, skipping search.")
        return []

    if keys_to_try is None:
        keys_to_try = tavily_api_keys[:]
        random.shuffle(keys_to_try)

    i = 0
    while i < len(keys_to_try):
        key = keys_to_try[i]
        key_exhausted = False
        try:
            client = AsyncTavilyClient(api_key=key)
            # Use topic="news" and time_range="week" to prioritize recent results
            response = await client.search(
                query=query,
                search_depth="basic",
                max_results=10,
                topic="news",
                time_range="week",
            )

            if len(response.get("results", [])) < 2:
                # If too few recent news results (e.g. historical facts, science),
                # retry with NO topic and NO time filter so Wikipedia etc. are included
                response = await client.search(
                    query=query,
                    max_results=num_results,
                    search_depth="basic",
                )   

            results = []

            for item in response.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("content", ""),
                    "source": item.get("url", "").split("/")[2] if item.get("url") else "Unknown",
                    "publish_date": item.get("published_date", ""),
                })

            return results

        except Exception as e:
            err = str(e)
            if "429" in err or "rate limit" in err.lower() or "unauthorized" in err.lower() or "401" in err:
                print(f"⚠️ Tavily key failed: {err}, trying next key...")
                keys_to_try.pop(i)
                key_exhausted = True
            else:
                print(f"⚠️ Tavily search failed: {e}")
                return []
        
        if not key_exhausted:
            i += 1

    return []

async def parallel_search(query, num_results=5):
    parallel_key = os.getenv("PARALLEL_API_KEY", "").strip()
    if not parallel_key:
        print("⚠️ No Parallel API key found, skipping search.")
        return []

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
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
                timeout=15.0,
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
        date = r.get('publish_date', '')
        date_str = f" (Published: {date})" if date else " (Published: date unknown)"
        lines.append(f"{i}. {r['source']}{date_str}: {r['title']}")
        lines.append(f"   URL: {r['url']}")
        desc = (r['description'] or '')[:500]
        lines.append(f"   Summary: {desc}")
        lines.append("")
    return "\n".join(lines)
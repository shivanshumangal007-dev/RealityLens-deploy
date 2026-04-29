import os
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException
import sys
import io
import time
import requests
import os
import json
import random
from google import genai
from google.genai import types
from PIL import Image
from dotenv import load_dotenv
from groq import Groq
from tavily import TavilyClient
import asyncio
from concurrent.futures import ThreadPoolExecutor
import base64
import getKeys


def call_groq_vision(prompt, image_bytes):
    """Groq vision fallback for extraction when Gemini fails."""
    if not getKeys.groq_api_key:
        return None, "GROQ_API_KEY is missing."

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    groq_client = Groq(api_key=groq_api_key)

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




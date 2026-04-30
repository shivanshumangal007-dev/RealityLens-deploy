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



def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)

env_path = resource_path(".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()


tavily_api_key = os.getenv("TAVILY_API_KEY", "").strip()
gemini_api_keys = os.getenv("GEMINI_API_KEY", "").split(",")
gemini_api_keys = [k.strip() for k in gemini_api_keys if k.strip()]
groq_api_key = os.getenv("GROQ_API_KEY", "").strip()


GROQ_MODELS = [
    "llama-3.3-70b-versatile",        # Best quality, large context
    "moonshotai/kimi-k2-instruct",    # Strong reasoning, huge context
    "qwen/qwen3-32b",                 # Good at structured JSON output
    "meta-llama/llama-4-scout-17b-16e-instruct",  # Fast fallback
    "llama-3.1-8b-instant",           # Last resort, very fast
]

GEMINI_MODELS = [
    "gemini-2.5-flash",
]

vision_models = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
]

def get_gemini_client(api_key):
    return genai.Client(api_key=api_key)
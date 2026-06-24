import os
import sys
from google import genai
from dotenv import load_dotenv


#find the env file regardless of where the file is run
#before we had a standalone app but now we only have the one connected to the server so this is unneccesary but as they say dont fix it if it aint broke
def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


#trying to find .env file
env_path = resource_path(".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()


#getting the api keys from the .env file
tavily_api_keys = os.getenv("TAVILY_API_KEY", "").split(",")
tavily_api_keys = [k.strip() for k in tavily_api_keys if k.strip()]
gemini_api_keys = os.getenv("GEMINI_API_KEY", "").split(",")
gemini_api_keys = [k.strip() for k in gemini_api_keys if k.strip()]
groq_api_keys = os.getenv("GROQ_API_KEY", "").split(",")
groq_api_keys = [k.strip() for k in groq_api_keys if k.strip()]
openrouter_api_keys = os.getenv("OPENROUTER_API_KEY", "").split(",")
openrouter_api_keys = [k.strip() for k in openrouter_api_keys if k.strip()]


#groq models to try
GROQ_MODELS = [
    "llama-3.3-70b-versatile",        # Best quality, large context
    "google/gemma-4-31b-it:free",     # Fast fallback (OpenRouter)
    "llama-3.1-8b-instant",           # Last resort, very fast
]

#gemini models to try
GEMINI_MODELS = [
    "gemini-2.5-flash",
]

#vision models to try
vision_models = [
    "qwen/qwen3.6-27b"
]
#function to get the gemini client 
def get_gemini_client(api_key):
    return genai.Client(api_key=api_key)
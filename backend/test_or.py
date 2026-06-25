import asyncio
from groq import AsyncGroq
import os
from dotenv import load_dotenv

load_dotenv()
or_key = os.getenv("OPENROUTER_API_KEY")

async def main():
    client = AsyncGroq(api_key=or_key, base_url="https://openrouter.ai/api/v1")
    try:
        response = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=10
        )
        print("SUCCESS")
    except Exception as e:
        with open("error.html", "w", encoding="utf-8") as f:
            f.write(str(e))
        print("ERROR WRITTEN TO FILE")

asyncio.run(main())

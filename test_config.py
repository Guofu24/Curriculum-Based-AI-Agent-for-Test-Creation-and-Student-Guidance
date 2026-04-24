"""Doc lap config tu .env nhu backend, test ket noi that su."""
import sys
sys.path.insert(0, "e:/D? án/Project/backend")

from app.core.config import get_settings
from openai import AsyncOpenAI
import asyncio

async def test():
    settings = get_settings()
    print(f"OPENAI_API_KEY = '{settings.OPENAI_API_KEY}'", flush=True)
    print(f"BASE_URL = '{settings.BASE_URL}'", flush=True)

    client = AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.BASE_URL,
    )
    try:
        resp = await client.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": "Say hi."}],
            max_tokens=20,
        )
        print(f"OK: {resp.choices[0].message.content}", flush=True)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)

asyncio.run(test())

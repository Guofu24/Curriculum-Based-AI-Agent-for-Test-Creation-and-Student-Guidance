"""Test API key giống hệt backend OpenAIProvider."""
from openai import AsyncOpenAI
import asyncio
import sys

# Lay tu .env nhu backend
API_KEY = "sk-bYYKTjtv0mePlRlw2jTDF5PfAssrlgozZSEC3OEAdLsSXh0u"
BASE_URL = "https://llm.wokushop.com/v1"


async def test():
    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)
    try:
        resp = await client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say hello in one sentence."}
            ],
            max_tokens=50,
        )
        print(f"OK: {resp.choices[0].message.content}", flush=True)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        sys.exit(1)


asyncio.run(test())

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.config import settings

_client = AsyncOpenAI(
    api_key=settings.GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

MODEL = "llama-3.3-70b-versatile"


async def stream_chat(messages: list[dict]) -> AsyncIterator[str]:
    """Yield text chunks from the LLM as they arrive."""
    stream = await _client.chat.completions.create(
        model=MODEL,
        messages=messages,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta

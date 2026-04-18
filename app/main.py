from fastapi import FastAPI

app = FastAPI(
    title="LLM Chat API",
    description="LLM-powered chat service with conversation history",
    version="0.1.0",
)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}

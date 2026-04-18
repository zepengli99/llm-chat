import asyncio
import json
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.logging_config import add_log_listener, configure_logging, remove_log_listener
from app.routers import auth, chat

configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="LLM Chat API",
    description="""
LLM-powered chat service with persistent conversation history and JWT authentication.

## Authentication

Most endpoints require a **JWT bearer token**. To get one:

1. **`POST /auth/register`** — create an account.
2. **`POST /auth/login`** — exchange credentials for a token.
3. Click **Authorize** (🔒) at the top of this page, enter `Bearer <token>`, then all
   protected endpoints will include the header automatically.

## Chat (streaming)

`POST /chat` streams the LLM reply as **Server-Sent Events**. Swagger UI's "Try it out"
sends the request but does not render the live stream — use `curl -N` or open
`test_ui.html` in a browser to see tokens arrive in real time.

## Dev tools

`GET /logs/stream` streams structured log entries as SSE — useful during local development.
It requires no authentication; **do not expose it in production**.
""",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    logger.info("%s %s %d  %.1fms", request.method, request.url.path, response.status_code, duration_ms)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(auth.router)
app.include_router(chat.router)


@app.get("/health", tags=["health"], summary="Health check")
async def health():
    """Returns `{"status": "ok"}` when the service is running. No authentication required."""
    return {"status": "ok"}


@app.get(
    "/logs/stream",
    tags=["dev"],
    summary="Stream live log entries (dev only)",
    response_description="Server-Sent Events stream of structured log entries.",
)
async def stream_logs() -> StreamingResponse:
    """
    Stream structured log entries from the running application as **Server-Sent Events**.

    Each event is a JSON object:
    ```
    data: {"time": "10:23:01", "level": "INFO", "name": "app.routers.chat", "message": "..."}
    ```

    **Intended for local development only — no authentication is required.**
    Remove or gate this endpoint before deploying to production.

    ```bash
    curl -N http://localhost:8000/logs/stream
    ```
    """
    async def generator():
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        add_log_listener(q)
        try:
            while True:
                entry = await q.get()
                yield f"data: {json.dumps(entry)}\n\n"
        finally:
            remove_log_listener(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

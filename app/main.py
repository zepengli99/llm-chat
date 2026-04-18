import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.logging_config import configure_logging
from app.routers import auth, chat

configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="LLM Chat API",
    description="LLM-powered chat service with conversation history",
    version="0.1.0",
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


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}

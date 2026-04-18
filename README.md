# LLM Chat API

A minimal LLM-powered chat API service with conversation history and JWT authentication.

Built with FastAPI, PostgreSQL, and Groq (free LLM inference).

## Quick Start

```bash
cp .env.example .env
# Edit .env and fill in your GROQ_API_KEY (get one free at https://console.groq.com)

docker compose up --build
```

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| Interactive docs (Swagger) | http://localhost:8000/docs |
| Adminer (DB web UI) | http://localhost:8080 |

**Adminer login** — System: `PostgreSQL`, Server: `db`, Username/Password/Database: `llmchat`

Database migrations run automatically on startup via `alembic upgrade head`.

## Running Tests

```bash
pip install -r requirements-dev.txt
```

**Fast (SQLite in-memory, no Docker needed):**

```bash
pytest
```

**Against Docker PostgreSQL (same database as production):**

```powershell
# Windows PowerShell — requires `docker compose up db` first
$env:DATABASE_URL="postgresql+asyncpg://llmchat:llmchat@localhost:5433/llmchat"; python -m pytest
```

> Note: the Docker db service is mapped to port **5433** to avoid conflicts with any local PostgreSQL instance on 5432.

The test suite covers authentication: register, login, duplicate email, invalid input, wrong password, and JWT format validation.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/register` | No | Register a new user |
| POST | `/auth/login` | No | Login and get JWT token |
| POST | `/chat` | Yes | Send a message, get streaming LLM response |
| GET | `/chat/history` | Yes | Retrieve conversation history |

## Design Decisions

**PostgreSQL** over SQLite — supports concurrent connections, proper foreign key constraints, and realistic indexing. Runs as a Docker service alongside the app.

**Groq** as LLM provider — free tier, no credit card required, OpenAI-compatible API, fast inference ideal for streaming demos.

**Server-Sent Events (SSE)** over WebSocket — simpler protocol for one-directional streaming (server → client), HTTP-native, easier to test with `curl`.

**Async SQLAlchemy** — matches FastAPI's async model; avoids blocking the event loop on DB queries.

## Project Structure

```
app/
├── main.py          # FastAPI app entry point
├── config.py        # Settings loaded from .env
├── database.py      # Async DB engine and session
├── dependencies.py  # Shared dependencies (auth, db session)
├── models/          # SQLAlchemy ORM models (User, Conversation, Message)
├── schemas/         # Pydantic request/response models
├── routers/         # Route handlers (auth, chat)
└── services/        # Business logic (auth, LLM)
alembic/             # DB migrations (alembic upgrade head runs on startup)
tests/               # pytest tests
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `POSTGRES_USER/PASSWORD/DB` | Used by docker-compose |
| `JWT_SECRET_KEY` | Secret for signing JWT tokens |
| `JWT_EXPIRE_MINUTES` | Token expiry (default: 1440 = 24h) |
| `GROQ_API_KEY` | Groq API key |

## What I'd Do Next

- CI pipeline (GitHub Actions) — `pytest` already runs locally; wire it into `.github/workflows/`
- Rate limiting per user (e.g., `slowapi`)
- Structured logging with request timing
- Test coverage for `/chat` streaming and conversation history once those endpoints are complete

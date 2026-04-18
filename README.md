# LLM Chat API

A minimal LLM-powered chat API service with conversation history and JWT authentication.

Built with FastAPI, PostgreSQL, and Groq (free LLM inference).

## Quick Start

```bash
cp .env.example .env
# Edit .env and fill in your GROQ_API_KEY (get one free at https://console.groq.com)

docker-compose up --build
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

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
├── models/          # SQLAlchemy ORM models
├── schemas/         # Pydantic request/response models
├── routers/         # Route handlers (auth, chat)
└── services/        # Business logic (auth, LLM)
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

- Rate limiting per user
- Database migrations with Alembic
- CI pipeline (GitHub Actions) with linting and tests
- Structured logging with request timing

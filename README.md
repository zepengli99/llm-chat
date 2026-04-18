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

Tests require `GROQ_API_KEY` to be set in `.env` — chat tests call the real Groq API (no mocking).

**SQLite in-memory (no Docker needed):**

```bash
python -m pytest tests/
```

**Against Docker PostgreSQL (same database as production):**

```bash
# requires `docker compose up db` first
DATABASE_URL=postgresql+asyncpg://llmchat:llmchat@localhost:5433/llmchat python -m pytest tests/
```

```powershell
# Windows PowerShell
$env:DATABASE_URL="postgresql+asyncpg://llmchat:llmchat@localhost:5433/llmchat"; python -m pytest tests/
```

> The Docker db service maps to port **5433** locally to avoid conflicts with any existing PostgreSQL on 5432.

The test suite covers two modules (24 tests total):

- **Auth** — register, login, duplicate email, invalid input, wrong password, JWT format (8 tests, no external calls)
- **Chat** — SSE streaming, conversation creation and continuation, message persistence, data isolation between users, history list and detail, auth protection (16 tests, calls the real Groq API)

## Database Schema

### `users`

Stores registered user accounts. Passwords are saved as bcrypt hashes; email is globally unique and used as the login credential.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `email` | VARCHAR(255) | Unique, indexed |
| `hashed_password` | VARCHAR(255) | bcrypt hash |
| `created_at` | TIMESTAMPTZ | Auto-set on insert |

### `conversations`

Represents a single chat session belonging to a user. A new conversation is created automatically when `POST /chat` is called without a `conversation_id`. The `title` is derived from the first 50 characters of the opening message for display in the history list. Deleting a user cascades to all their conversations.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `user_id` | UUID | FK → `users.id` (CASCADE DELETE), indexed |
| `title` | VARCHAR(255) | First 50 chars of the opening message |
| `created_at` | TIMESTAMPTZ | Auto-set on insert |
| `updated_at` | TIMESTAMPTZ | Auto-updated on write |

### `messages`

A single message within a conversation. `role` distinguishes user input (`user`) from model replies (`assistant`). Messages are ordered by `created_at` and passed as the context window to the LLM, enabling multi-turn dialogue. Deleting a conversation cascades to all its messages.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `conversation_id` | UUID | FK → `conversations.id` (CASCADE DELETE), indexed |
| `role` | VARCHAR(20) | `"user"` or `"assistant"` |
| `content` | TEXT | Full message text |
| `created_at` | TIMESTAMPTZ | Auto-set on insert; used for ordering |

## API Endpoints

### `POST /auth/register`

Register a new user. Returns the created user's id and email.

**Request**
```json
{
  "email": "alice@example.com",
  "password": "secret123"
}
```

**Response** `201 Created`
```json
{
  "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "email": "alice@example.com"
}
```

**Error** `409 Conflict` — email already registered.

---

### `POST /auth/login`

Authenticate and receive a JWT bearer token.

**Request**
```json
{
  "email": "alice@example.com",
  "password": "secret123"
}
```

**Response** `200 OK`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Error** `401 Unauthorized` — wrong email or password.

---

### `POST /chat`

Send a message and stream the LLM reply via **Server-Sent Events**.

Pass `Authorization: Bearer <token>` in every request header.

Omit `conversation_id` to start a new conversation; include it to continue an existing one.

**Request**
```json
{
  "message": "What is the capital of France?",
  "conversation_id": null
}
```

**Response** — `text/event-stream`

Token chunks arrive as they are generated:
```
data: {"token": "The"}

data: {"token": " capital"}

data: {"token": " of France is Paris."}

data: {"done": true, "conversation_id": "a1b2c3d4-..."}
```

The final `done` event carries the `conversation_id` to use for follow-up messages.

**Error** `404 Not Found` — `conversation_id` does not exist or belongs to another user.

---

### `GET /chat/history`

List all conversations for the authenticated user, sorted by most recently updated.

**Response** `200 OK`
```json
[
  {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "title": "What is the capital of France?",
    "created_at": "2026-04-18T10:00:00Z",
    "updated_at": "2026-04-18T10:00:05Z"
  }
]
```

---

### `GET /chat/history/{conversation_id}`

Get a single conversation with its full message history, ordered by time.

**Response** `200 OK`
```json
{
  "conversation": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "title": "What is the capital of France?",
    "created_at": "2026-04-18T10:00:00Z",
    "updated_at": "2026-04-18T10:00:05Z"
  },
  "messages": [
    {
      "id": "b2c3d4e5-...",
      "role": "user",
      "content": "What is the capital of France?",
      "created_at": "2026-04-18T10:00:00Z"
    },
    {
      "id": "c3d4e5f6-...",
      "role": "assistant",
      "content": "The capital of France is Paris.",
      "created_at": "2026-04-18T10:00:05Z"
    }
  ]
}
```

**Error** `404 Not Found` — conversation does not exist or belongs to another user.

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
- Structured logging with request timing and correlation IDs
- Conversation title auto-generation via a short LLM summarisation call instead of the first-50-chars truncation

# LLM Chat API

A minimal LLM-powered chat API service with conversation history and JWT authentication.

Built with FastAPI, PostgreSQL, and Groq (free LLM inference).

## Architecture

```
                    ┌──────────────────────────────────────────────────┐
                    │              FastAPI App  (:8000)                 │
                    │                                                    │
Browser / curl ───▶ │  ┌─────────────┐  ┌──────────────┐  ┌─────────┐ │
test_ui.html        │  │ auth router │  │ chat router  │  │  logs/  │ │
(HTTP + SSE)        │  │ /auth/*     │  │ /chat/*      │  │ stream  │ │
                    │  │             │  │              │  │ (SSE)   │ │
                    │  │ register    │  │ POST /chat   │  └─────────┘ │
                    │  │ login       │  │ GET /history │       │       │
                    │  └──────┬──────┘  └──────┬───────┘       │       │
                    │         │                │     SSE tokens │       │
                    │  ┌──────▼────────────────▼──────┐         │       │
                    │  │  Async SQLAlchemy (asyncpg)  │         │       │
                    │  └──────────────┬───────────────┘         │       │
                    └─────────────────┼───────────────┬─────────┘───────┘
                                      │               │ HTTP streaming
                          ┌───────────▼──────┐  ┌─────▼──────────────────┐
                          │   PostgreSQL     │  │   Groq API (external)  │
                          │   :5432 (app)    │  │   llama-3.3-70b        │
                          │   :5433 (tests)  │  │   OpenAI-compat. API   │
                          │                  │  └────────────────────────┘
                          │   users          │
                          │   conversations  │
                          │   messages       │
                          └──────────────────┘
```

**Request flow for `POST /chat`:**

1. Client sends `{message, conversation_id?}` with a JWT Bearer token
2. Auth middleware verifies the JWT and extracts the user
3. Chat router loads conversation history from PostgreSQL
4. History + new message are forwarded to Groq as a streaming request
5. Tokens are flushed to the client as SSE chunks as they arrive
6. Once the stream ends, the full assistant reply is persisted to PostgreSQL
7. A final `{"done": true, "conversation_id": "..."}` event is sent

## Project Structure

```
app/
├── main.py           # FastAPI app entry point, CORS middleware, /logs/stream
├── config.py         # Settings loaded from .env
├── database.py       # Async DB engine and session factory
├── dependencies.py   # Shared FastAPI dependencies (JWT auth, DB session)
├── logging_config.py # Structured logging + broadcast handler for SSE log stream
├── models/           # SQLAlchemy ORM models (User, Conversation, Message)
├── schemas/          # Pydantic request/response models
├── routers/          # Route handlers (auth, chat)
└── services/         # Business logic (auth, LLM streaming)
alembic/              # DB migrations — runs automatically on startup
docker/
└── init.sql          # Creates the llmchat_test database on first container start
tests/                # pytest suite (24 tests, auth + chat)
test_ui.html          # Standalone browser UI — open directly, no build needed
.env.example          # Template — copy to .env and fill in GROQ_API_KEY
```

## Quick Start

**Prerequisites:** Docker and Docker Compose.

```bash
# 1. Copy env template and fill in your Groq API key
#    Get one free (no credit card) at https://console.groq.com
cp .env.example .env

# 2. Start all services (API + PostgreSQL + Adminer)
docker compose up --build
```

> **Schema changes** are handled automatically by Alembic — just restart the container (`docker compose up --build`) and migrations run on startup. **No volume wipe needed.**
>
> **Fresh start / reset** (only needed if the database is in a truly broken state):
> ```bash
> docker compose down -v   # wipes the postgres_data volume — destroys all data
> docker compose up --build
> ```
> Also required if `docker/init.sql` changed, since it only runs when the volume is first created (it creates the `llmchat_test` database for tests).

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| Interactive docs (Swagger) | http://localhost:8000/docs |
| Adminer (DB web UI) | http://localhost:8080 |

**Adminer login** — System: `PostgreSQL`, Server: `db`, Username/Password/Database: `llmchat`

Database migrations run automatically on startup via `alembic upgrade head` — no manual step needed.

**Quick smoke test** (API must be running):

```bash
# Register
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"secret123"}' | jq

# Login — copy the access_token from the response
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"secret123"}' | jq

# Chat (streaming)
curl -N http://localhost:8000/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message":"What is the capital of France?"}'
```

Or open `test_ui.html` in a browser for an interactive UI — no build step required.

## Running Tests

```bash
pip install -r requirements-dev.txt
```

Tests require `GROQ_API_KEY` in `.env` — chat tests call the real Groq API (no mocking; see [Design Decisions](#design-decisions--trade-offs)).

**SQLite in-memory (no Docker needed):**

```bash
python -m pytest tests/
```

**Against Docker PostgreSQL (dedicated test database):**

```bash
# Requires `docker compose up db` first
python -m pytest tests/
```

`TEST_DATABASE_URL` is preset in `.env.example` to point at the `llmchat_test` database on port 5433. The test suite creates its schema at session start and drops it at the end — it never touches the `llmchat` production database.

**Overriding the URL inline** (e.g. CI without a `.env` file):

```bash
# Linux / macOS
TEST_DATABASE_URL="postgresql+asyncpg://llmchat:llmchat@localhost:5433/llmchat_test" python -m pytest tests/

# Windows PowerShell
$env:TEST_DATABASE_URL="postgresql+asyncpg://llmchat:llmchat@localhost:5433/llmchat_test"; python -m pytest tests/
```

> The Docker db service maps to port **5433** locally to avoid conflicts with any existing PostgreSQL on 5432.

**Test coverage (24 tests total):**

| Module | Tests | External calls |
|--------|-------|---------------|
| Auth — register, login, duplicate email, invalid input, wrong password, JWT format | 8 | None |
| Chat — SSE streaming, conversation create/continue, message persistence, user isolation, history list/detail, auth protection | 16 | Groq API |

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

A single message within a conversation. `role` distinguishes user input (`user`) from model replies (`assistant`). Messages are ordered by `created_at` and passed as the full context window to the LLM, enabling multi-turn dialogue. Deleting a conversation cascades to all its messages.

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
{ "email": "alice@example.com", "password": "secret123" }
```

**Response** `201 Created`
```json
{ "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479", "email": "alice@example.com" }
```

**Errors:** `409 Conflict` — email already registered · `422 Unprocessable Entity` — invalid input

---

### `POST /auth/login`

Authenticate and receive a JWT bearer token (valid for 24 h by default).

**Request**
```json
{ "email": "alice@example.com", "password": "secret123" }
```

**Response** `200 OK`
```json
{ "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...", "token_type": "bearer" }
```

**Error:** `401 Unauthorized` — wrong email or password

---

### `POST /chat`

Send a message and stream the LLM reply via **Server-Sent Events**.

Pass `Authorization: Bearer <token>` in every request header.

Omit `conversation_id` to start a new conversation; include it to continue an existing one.

**Request**
```json
{ "message": "What is the capital of France?", "conversation_id": null }
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

**Errors:** `401 Unauthorized` — missing/invalid token · `404 Not Found` — `conversation_id` not found or belongs to another user

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
    { "id": "b2c3d4e5-...", "role": "user",      "content": "What is the capital of France?", "created_at": "2026-04-18T10:00:00Z" },
    { "id": "c3d4e5f6-...", "role": "assistant", "content": "The capital of France is Paris.", "created_at": "2026-04-18T10:00:05Z" }
  ]
}
```

**Error:** `404 Not Found` — conversation does not exist or belongs to another user

---

### `GET /logs/stream`

Stream live structured log entries as **Server-Sent Events**. Intended for local development and debugging only — **no auth required; do not expose in production**.

```
data: {"time": "10:23:01", "level": "INFO", "name": "app.routers.chat", "message": "llm stream started  conversation=..."}
data: {"time": "10:23:03", "level": "INFO", "name": "app.routers.chat", "message": "llm stream complete conversation=...  tokens=42"}
```

```bash
curl -N http://localhost:8000/logs/stream
```

## Browser Test UI

`test_ui.html` is a standalone single-file UI for exercising the API without any tooling. Open it directly in a browser (no build step, no server needed):

- **Auth panel** — register a user and log in; the returned JWT is saved automatically
- **Chat panel** — send messages, stream token-by-token replies via SSE, continue existing conversations
- **Log panel** — connects to `GET /logs/stream` and shows live structured log entries in real time

The page assumes the API is running at `http://localhost:8000`. Change the `BASE` constant at the top of the file to point elsewhere.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (used by the running app) |
| `TEST_DATABASE_URL` | PostgreSQL connection string for the isolated test database |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Docker Compose DB container initialisation |
| `JWT_SECRET_KEY` | Secret for signing JWT tokens — change before deploying |
| `JWT_EXPIRE_MINUTES` | Token lifetime in minutes (default: `1440` = 24 h) |
| `GROQ_API_KEY` | Groq API key — get one free at https://console.groq.com |

## Design Decisions & Trade-offs

**PostgreSQL over SQLite**
Chosen for concurrent connections, proper foreign-key constraints, and realistic indexing under multi-user load. The trade-off is added setup complexity (Docker service required). SQLite is used automatically in tests when no `TEST_DATABASE_URL` is set, so contributors can run the auth tests without Docker.

**Groq as LLM provider**
Free tier, no credit card, OpenAI-compatible API, and fast inference ideal for streaming demos. Trade-off: external dependency — tests that exercise the chat flow call the real Groq API rather than a mock. This catches real integration failures (token format, stream errors) at the cost of test speed and network dependency.

**Server-Sent Events over WebSockets**
SSE is a simpler, HTTP-native protocol for one-directional server→client streaming. It needs no handshake, works through standard HTTP proxies, and is trivially testable with `curl`. Trade-off: SSE is unidirectional — if bidirectional messaging (e.g. cancel mid-stream) is needed later, a WebSocket upgrade would be required.

**Async SQLAlchemy with asyncpg**
Matches FastAPI's async model and avoids blocking the event loop on DB queries. Trade-off: the async SQLAlchemy API is more verbose than its sync counterpart, and some ORM features (e.g. lazy loading) behave differently.

**SSE generator owns its own DB session**
`_sse_generator` opens and closes its own `AsyncSessionLocal` rather than sharing the route handler's session. FastAPI closes the route's session before streaming finishes, so sharing it would cause detached-instance errors on long-running streams. Trade-off: the generator must manage its own session lifecycle carefully.

**Full conversation history as LLM context**
Every message in the conversation is sent to Groq on each request. This gives the model full context for multi-turn dialogue but grows linearly with conversation length. For very long conversations this will exceed the model's context window and increase latency. A rolling-window or summarisation strategy would be needed at scale.

**CORS enabled for all origins**
Required for `test_ui.html` served from `file://`, which triggers the browser's CORS policy. **Restrict `allow_origins` to specific domains before deploying to production.**

## What I'd Do Next

- **CI pipeline** (GitHub Actions) — `pytest` already runs locally; wire it into `.github/workflows/`
- **Rate limiting per user** — e.g. `slowapi` to prevent API abuse
- **Rolling context window** — cap the history sent to the LLM instead of growing unbounded
- **Conversation title generation** — short LLM summarisation call instead of the first-50-chars truncation
- **Restrict CORS** `allow_origins` to specific domains before production deployment
- **Gate `GET /logs/stream`** behind authentication or remove it entirely in production builds

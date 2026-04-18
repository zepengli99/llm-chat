"""
Tests for /chat and /chat/history endpoints.

These tests call the real Groq API via GROQ_API_KEY (read from .env).
"""
import json
import uuid

import pytest_asyncio
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_sse(text: str) -> list[dict]:
    """Parse SSE response body into a list of event payloads."""
    events = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict:
    """Register a fresh user and return Bearer auth headers."""
    email = f"chatuser_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/auth/register", json={"email": email, "password": "password123"})
    resp = await client.post("/auth/login", json={"email": email, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def second_auth_headers(client: AsyncClient) -> dict:
    """A second independent user, used to test ownership checks."""
    email = f"other_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/auth/register", json={"email": email, "password": "password123"})
    resp = await client.post("/auth/login", json={"email": email, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth protection
# ---------------------------------------------------------------------------

async def test_chat_requires_auth(client: AsyncClient):
    resp = await client.post("/chat", json={"message": "hi"})
    assert resp.status_code in (401, 403)


async def test_history_list_requires_auth(client: AsyncClient):
    resp = await client.get("/chat/history")
    assert resp.status_code in (401, 403)


async def test_history_detail_requires_auth(client: AsyncClient):
    resp = await client.get(f"/chat/history/{uuid.uuid4()}")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /chat — SSE streaming
# ---------------------------------------------------------------------------

async def test_chat_returns_sse_tokens(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/chat", json={"message": "hi"}, headers=auth_headers)

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    events = parse_sse(resp.text)
    token_events = [e for e in events if "token" in e]
    assert len(token_events) > 0
    assert all(isinstance(e["token"], str) for e in token_events)


async def test_chat_final_event_has_done_and_conversation_id(
    client: AsyncClient, auth_headers: dict
):
    resp = await client.post("/chat", json={"message": "hello"}, headers=auth_headers)

    events = parse_sse(resp.text)
    done_events = [e for e in events if e.get("done") is True]
    assert len(done_events) == 1
    assert "conversation_id" in done_events[0]
    # Must be a valid UUID
    uuid.UUID(done_events[0]["conversation_id"])


async def test_chat_creates_new_conversation_when_no_id_given(
    client: AsyncClient, auth_headers: dict
):
    resp = await client.post("/chat", json={"message": "first message"}, headers=auth_headers)

    events = parse_sse(resp.text)
    conv_id = next(e["conversation_id"] for e in events if "conversation_id" in e)

    # Conversation should now appear in history
    hist = await client.get("/chat/history", headers=auth_headers)
    ids = [c["id"] for c in hist.json()]
    assert conv_id in ids


async def test_chat_continues_existing_conversation(
    client: AsyncClient, auth_headers: dict
):
    resp1 = await client.post("/chat", json={"message": "first"}, headers=auth_headers)

    events1 = parse_sse(resp1.text)
    conv_id = next(e["conversation_id"] for e in events1 if "conversation_id" in e)

    resp2 = await client.post(
        "/chat",
        json={"message": "second", "conversation_id": conv_id},
        headers=auth_headers,
    )

    events2 = parse_sse(resp2.text)
    returned_id = next(e["conversation_id"] for e in events2 if "conversation_id" in e)
    assert returned_id == conv_id

    # History should have 4 messages: user, assistant, user, assistant
    detail = await client.get(f"/chat/history/{conv_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) == 4


async def test_chat_invalid_conversation_id_returns_404(
    client: AsyncClient, auth_headers: dict
):
    resp = await client.post(
        "/chat",
        json={"message": "hi", "conversation_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_chat_cannot_access_another_users_conversation(
    client: AsyncClient, auth_headers: dict, second_auth_headers: dict
):
    resp = await client.post("/chat", json={"message": "mine"}, headers=auth_headers)

    conv_id = next(e["conversation_id"] for e in parse_sse(resp.text) if "conversation_id" in e)

    # Second user tries to post into first user's conversation
    steal = await client.post(
        "/chat",
        json={"message": "steal", "conversation_id": conv_id},
        headers=second_auth_headers,
    )
    assert steal.status_code == 404


# ---------------------------------------------------------------------------
# GET /chat/history — conversation list
# ---------------------------------------------------------------------------

async def test_history_list_empty_for_new_user(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/chat/history", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_history_list_returns_conversations(client: AsyncClient, auth_headers: dict):
    await client.post("/chat", json={"message": "msg1"}, headers=auth_headers)
    await client.post("/chat", json={"message": "msg2"}, headers=auth_headers)

    resp = await client.get("/chat/history", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_history_list_does_not_include_other_users(
    client: AsyncClient, auth_headers: dict, second_auth_headers: dict
):
    await client.post("/chat", json={"message": "user1 msg"}, headers=auth_headers)
    await client.post("/chat", json={"message": "user2 msg"}, headers=second_auth_headers)

    resp = await client.get("/chat/history", headers=auth_headers)
    assert len(resp.json()) == 1


async def test_history_list_conversation_has_title(client: AsyncClient, auth_headers: dict):
    await client.post("/chat", json={"message": "My first question"}, headers=auth_headers)

    resp = await client.get("/chat/history", headers=auth_headers)
    assert resp.json()[0]["title"] == "My first question"


# ---------------------------------------------------------------------------
# GET /chat/history/{conversation_id} — conversation detail
# ---------------------------------------------------------------------------

async def test_history_detail_returns_messages(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/chat", json={"message": "test"}, headers=auth_headers)

    conv_id = next(e["conversation_id"] for e in parse_sse(resp.text) if "conversation_id" in e)

    detail = await client.get(f"/chat/history/{conv_id}", headers=auth_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["conversation"]["id"] == conv_id
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "test"
    assert body["messages"][1]["role"] == "assistant"
    assert len(body["messages"][1]["content"]) > 0


async def test_history_detail_not_found(client: AsyncClient, auth_headers: dict):
    resp = await client.get(f"/chat/history/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


async def test_history_detail_other_users_conversation_returns_404(
    client: AsyncClient, auth_headers: dict, second_auth_headers: dict
):
    resp = await client.post("/chat", json={"message": "private"}, headers=auth_headers)

    conv_id = next(e["conversation_id"] for e in parse_sse(resp.text) if "conversation_id" in e)

    detail = await client.get(f"/chat/history/{conv_id}", headers=second_auth_headers)
    assert detail.status_code == 404

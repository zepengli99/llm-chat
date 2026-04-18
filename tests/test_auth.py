from httpx import AsyncClient


async def test_register_success(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert "id" in body
    assert "hashed_password" not in body


async def test_register_duplicate_email(client: AsyncClient):
    payload = {"email": "bob@example.com", "password": "password123"}
    await client.post("/auth/register", json=payload)
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 409
    assert "already registered" in response.json()["detail"]


async def test_register_invalid_email(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "password123"},
    )
    assert response.status_code == 422


async def test_register_password_too_short(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={"email": "charlie@example.com", "password": "short"},
    )
    assert response.status_code == 422


async def test_login_success(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"email": "dave@example.com", "password": "mysecret123"},
    )
    response = await client.post(
        "/auth/login",
        json={"email": "dave@example.com", "password": "mysecret123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"email": "eve@example.com", "password": "correctpass1"},
    )
    response = await client.post(
        "/auth/login",
        json={"email": "eve@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401


async def test_login_nonexistent_user(client: AsyncClient):
    response = await client.post(
        "/auth/login",
        json={"email": "ghost@example.com", "password": "anything123"},
    )
    assert response.status_code == 401


async def test_login_token_is_valid_jwt(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"email": "frank@example.com", "password": "password123"},
    )
    response = await client.post(
        "/auth/login",
        json={"email": "frank@example.com", "password": "password123"},
    )
    token = response.json()["access_token"]
    # JWT is always 3 dot-separated base64 segments
    assert len(token.split(".")) == 3

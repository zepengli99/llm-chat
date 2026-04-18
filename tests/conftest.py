import os

# If DATABASE_URL is set in environment, use it (e.g. Docker PostgreSQL).
# Otherwise fall back to in-memory SQLite so plain `pytest` needs no infra.
_DB_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ["DATABASE_URL"] = _DB_URL

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool, NullPool

from app.database import get_db
from app.main import app
from app.models import Base

_is_sqlite = _DB_URL.startswith("sqlite")


@pytest_asyncio.fixture(scope="session")
async def engine():
    kwargs = (
        {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
        if _is_sqlite
        else {"poolclass": NullPool}
    )
    eng = create_async_engine(_DB_URL, **kwargs)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    yield eng
    async with eng.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all, checkfirst=True)
        pass
    await eng.dispose()


@pytest_asyncio.fixture
async def client(engine):
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()

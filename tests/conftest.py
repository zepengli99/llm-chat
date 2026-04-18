import os

# Priority: TEST_DATABASE_URL > SQLite in-memory (never touch the production DB).
_DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
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
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        pass
        # await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def client(engine):
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    # _sse_generator opens its own sessions via AsyncSessionLocal, bypassing
    # get_db. Patch it to use the same test session factory so it hits the
    # same in-memory database as the rest of the test.
    import app.routers.chat as chat_module
    original_session_local = chat_module.AsyncSessionLocal
    chat_module.AsyncSessionLocal = session_factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    chat_module.AsyncSessionLocal = original_session_local
    app.dependency_overrides.clear()

    # Wipe all rows after each test so tests don't interfere with each other.
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())

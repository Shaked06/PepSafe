"""Pytest configuration and fixtures."""

import asyncio
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Set test environment BEFORE importing app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_pepper.db"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["OPENWEATHERMAP_API_KEY"] = "test_key"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Track if DB is initialized
_db_initialized = False


async def _ensure_db():
    """Ensure database is initialized."""
    global _db_initialized
    if not _db_initialized:
        from sqlmodel import SQLModel
        from app.db.session import engine
        # Import models to register them with SQLModel metadata
        from app.db import models  # noqa: F401

        # Remove existing test database
        test_db = "./test_pepper.db"
        if os.path.exists(test_db):
            os.remove(test_db)

        # Create all tables
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        _db_initialized = True


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Create test client with database."""
    await _ensure_db()

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as test_client:
        yield test_client

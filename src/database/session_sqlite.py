from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.database import Base

SQLITE_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

sqlite_engine = create_async_engine(
    SQLITE_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

AsyncSQLiteSessionLocal = async_sessionmaker(
    bind=sqlite_engine,
    autoflush=False,
    expire_on_commit=False,
)


async def get_sqlite_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSQLiteSessionLocal() as session:
        yield session


@asynccontextmanager
async def get_sqlite_db_contextmanager() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSQLiteSessionLocal() as session:
        yield session


async def reset_sqlite_database() -> None:
    async with sqlite_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

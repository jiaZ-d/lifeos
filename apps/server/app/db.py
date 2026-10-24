"""Async SQLAlchemy engine / session."""
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"timeout": 30},  # wait up to 30s for SQLite write lock
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")  # readers don't block writer
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create tables on startup + lightweight column migrations (v1: pre-Alembic)."""
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # --- inline migrations for columns added after first release ---
        from sqlalchemy import text

        def _has_column(columns: list, name: str) -> bool:
            return any(c[1] == name for c in columns)

        res = await conn.execute(text("PRAGMA table_info(projections)"))
        cols = res.fetchall()
        if cols and not _has_column(cols, "suggestions_json"):
            await conn.execute(text("ALTER TABLE projections ADD COLUMN suggestions_json JSON"))

"""Debug: check how aware datetimes are stored/queried in SQLite via SQLAlchemy."""
import asyncio
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Entry


async def main():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    async with Session() as s:
        e = Entry(user_id=1, categories=["study"], primary_category="study", content="x")
        s.add(e)
        await s.commit()
        print("stored created_at:", e.created_at, "| tzinfo:", e.created_at.tzinfo)
        start = dt.date.today()
        lo = dt.datetime.combine(start, dt.time.min, tzinfo=dt.timezone.utc)
        hi = dt.datetime.combine(start + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc)
        rows = (await s.execute(select(Entry).where(Entry.created_at >= lo, Entry.created_at < hi))).scalars().all()
        print("aware-range query hits:", len(rows))
        lo2 = dt.datetime.combine(start, dt.time.min)
        hi2 = dt.datetime.combine(start + dt.timedelta(days=1), dt.time.min)
        rows2 = (await s.execute(select(Entry).where(Entry.created_at >= lo2, Entry.created_at < hi2))).scalars().all()
        print("naive-range query hits:", len(rows2))
    await eng.dispose()


asyncio.run(main())

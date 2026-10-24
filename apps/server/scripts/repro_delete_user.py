"""Reproduce user deletion on a COPY of the live DB (safe)."""
import asyncio
import shutil
import sqlite3
import sys

sys.path.insert(0, r"D:\ai\code\lifeos\apps\server")

SRC = r"D:\ai\code\lifeos\data\lifeos.db"
DST = r"D:\ai\code\lifeos\apps\server\.tmp-run\del-repro\copy.db"
shutil.copy(SRC, DST)


async def main():
    import datetime as dt

    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db import Base
    from app.api.auth import _delete_user_data

    eng = create_async_engine(f"sqlite+aiosqlite:///{DST}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    async with Session() as db:
        from sqlalchemy import select
        from app.models import User

        u = (await db.execute(select(User).where(User.username == "tmpuser01"))).scalar_one()
        print("target:", u.id, u.username)
        await _delete_user_data(db, u.id)
        await db.delete(u)
        await db.commit()
        print("deleted OK")
    await eng.dispose()

    c = sqlite3.connect(DST)
    print("users now:", c.execute("SELECT id, username FROM users").fetchall())
    print("stray entries:", c.execute("SELECT COUNT(*) FROM entries WHERE user_id=4").fetchone())
    c.close()


asyncio.run(main())

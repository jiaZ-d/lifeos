"""Manual debug: goal progress computation."""
import asyncio
import datetime as dt
import uuid
from pathlib import Path

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app

tmp = Path(__file__).resolve().parents[2] / ".tmp-run" / "dbg"
tmp.mkdir(parents=True, exist_ok=True)


async def main():
    import app.db as appdb

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp}/dbg.db")
    appdb.engine = eng
    appdb.SessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/auth/register", json={"username": "dbg", "password": "pass123456"})
            h = {"Authorization": f"Bearer {r.json()['token']}"}
            g = (await c.post("/api/goals", json={"title": "g"}, headers=h)).json()
            yt = (await c.post("/api/tasks", json={"goal_id": g["id"], "granularity": "year", "title": "y"}, headers=h)).json()
            mt = (await c.post("/api/tasks", json={"parent_task_id": yt["id"], "granularity": "month", "title": "m"}, headers=h)).json()
            a = (await c.post("/api/actions", json={"task_id": mt["id"], "title": "act", "minutes": 30, "date": dt.date.today().isoformat()}, headers=h)).json()
            await c.post(f"/api/actions/{a['id']}/complete", headers=h)
            print("ACTIONS:", (await c.get("/api/actions", headers=h)).json())
            print("TASKS:", (await c.get("/api/tasks", headers=h)).json())
            print("GOALS:", (await c.get("/api/goals", headers=h)).json())
    await eng.dispose()


asyncio.run(main())

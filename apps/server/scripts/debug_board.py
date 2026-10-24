import uuid
"""Debug goal derived status."""
import asyncio, uuid
from pathlib import Path
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app

tmp = Path(r"D:\ai\code\lifeos\apps\server\.tmp-run") / ("dbg" + str(uuid.uuid4())[:8])
tmp.mkdir(parents=True, exist_ok=True)

async def main():
    import app.db as appdb
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp}/t.db")
    appdb.engine = eng
    appdb.SessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/auth/register", json={"username": "dbg", "password": "pass123456"})
            h = {"Authorization": f"Bearer {r.json()['token']}"}
            g = (await c.post("/api/goals", json={"title": "g"}, headers=h)).json()
            sub = (await c.post("/api/tasks", json={"goal_id": g["id"], "granularity": "year", "title": "sub"}, headers=h)).json()
            mt = (await c.post("/api/tasks", json={"parent_task_id": sub["id"], "granularity": "month", "title": "m"}, headers=h)).json()
            r = await c.post(f"/api/tasks/{sub['id']}/decompose", json={}, headers=h)
            print("decompose children:", len(r.json()["children"]))
            import datetime as dt
            a1 = (await c.post("/api/actions", json={"task_id": mt["id"], "title": "a1", "minutes": 30, "date": dt.date.today().isoformat()}, headers=h)).json()
            await c.post("/api/actions", json={"task_id": mt["id"], "title": "a2", "minutes": 30, "date": dt.date.today().isoformat()}, headers=h)
            await c.post(f"/api/actions/{a1['id']}/complete", headers=h)
            b = (await c.get("/api/board?dimension=goal", headers=h)).json()
            print("GOAL COLS:", {k: [c['id'] for c in v] for k, v in b['columns'].items()})
            b2 = (await c.get("/api/board?dimension=sub", headers=h)).json()
            print("SUB COLS:", {k: [c['id'] for c in v] for k, v in b2['columns'].items()})
            b3 = (await c.get("/api/board?dimension=month", headers=h)).json()
            print("MONTH COLS:", {k: [c['id'] for c in v] for k, v in b3['columns'].items()})
    await eng.dispose()

asyncio.run(main())

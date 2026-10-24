"""Debug heatmap/trend zero counts."""
import asyncio
import uuid
from pathlib import Path

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app

tmp = Path(r"D:\ai\code\lifeos\apps\server\.tmp-run") / ("hdbg" + str(uuid.uuid4())[:8])
tmp.mkdir(parents=True, exist_ok=True)


async def main():
    import app.db as appdb
    import datetime as dt

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp}/t.db")
    appdb.engine = eng
    appdb.SessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/auth/register", json={"username": "hdbg", "password": "pass123456"})
            h = {"Authorization": f"Bearer {r.json()['token']}"}
            today = dt.date.today().isoformat()
            a = (await c.post("/api/actions", json={"title": "x", "minutes": 30, "date": today}, headers=h)).json()
            rr = await c.post(f"/api/actions/{a['id']}/complete", headers=h)
            print("complete:", rr.json().get("status"), rr.json().get("done_at"))
            hm = (await c.get("/api/stats/heatmap", headers=h)).json()
            print("heatmap:", hm)
            tr = (await c.get("/api/stats/trend", headers=h)).json()
            print("trend summary:", tr["summary"])
    await eng.dispose()

asyncio.run(main())

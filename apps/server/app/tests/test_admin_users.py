"""Admin user management: list + delete user with full data cleanup."""
import uuid
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app

_RUN_TMP = Path(__file__).resolve().parents[3] / ".tmp-run"


@pytest.fixture
async def client(monkeypatch):
    test_dir = _RUN_TMP / uuid.uuid4().hex[:8]
    test_dir.mkdir(parents=True, exist_ok=True)
    import app.db as appdb

    eng = create_async_engine(f"sqlite+aiosqlite:///{test_dir}/test.db")
    appdb.engine = eng
    appdb.SessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    await eng.dispose()
    import shutil

    shutil.rmtree(test_dir, ignore_errors=True)


async def _register(client, username):
    r = await client.post(
        "/api/auth/register", json={"username": username, "password": "pass123456"}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_admin_can_list_and_delete_user(client):
    admin = await _register(client, "admin1")
    ah = {"Authorization": f"Bearer {admin['token']}"}
    bob = await _register(client, "bob")
    bh = {"Authorization": f"Bearer {bob['token']}"}
    # bob has data
    await client.post("/api/entries", json={"categories": ["study"], "content": "x"}, headers=bh)
    await client.post("/api/goals", json={"title": "bob goal"}, headers=bh)
    # non-admin cannot list/delete users
    r = await client.get("/api/auth/users", headers=bh)
    assert r.status_code == 403
    r = await client.delete(f"/api/auth/users/{bob['user_id']}", headers=bh)
    assert r.status_code == 403
    # admin lists users
    r = await client.get("/api/auth/users", headers=ah)
    assert {u["username"] for u in r.json()} == {"admin1", "bob"}
    # admin deletes bob
    r = await client.delete(f"/api/auth/users/{bob['user_id']}", headers=ah)
    assert r.json()["deleted"] == "bob"
    # bob's token invalid now; bob's data gone
    r = await client.get("/api/today", headers=bh)
    assert r.status_code == 401
    # cannot delete self
    r = await client.delete(f"/api/auth/users/{admin['user_id']}", headers=ah)
    assert r.status_code == 400
    # cannot delete last admin
    r = await client.delete(f"/api/auth/users/{admin['user_id']}", headers=ah)
    assert r.status_code == 400

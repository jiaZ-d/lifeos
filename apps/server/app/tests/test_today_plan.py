"""Tests for today auto-plan (issue #1)."""
import datetime as dt
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


async def _auth(client):
    r = await client.post(
        "/api/auth/register", json={"username": f"u{uuid.uuid4().hex[:6]}", "password": "pass123456"}
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_auto_plan_generates_and_dedupes(client):
    h = await _auth(client)
    today = dt.date.today().isoformat()
    t1 = (await client.post("/api/tasks", json={"granularity": "week", "title": "刷真题"}, headers=h)).json()
    t2 = (await client.post(
        "/api/tasks",
        json={"granularity": "week", "title": "复习错题", "due_date": today, "status": "doing"},
        headers=h,
    )).json()
    r = await client.post("/api/today/auto-plan", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["created"]) == 2
    assert data["created"][0]["task_id"] in (t1["id"], t2["id"])
    # second run: all tasks already have actions today -> nothing new
    r2 = await client.post("/api/today/auto-plan", headers=h)
    assert r2.json()["created"] == []
    # today view shows them
    today_data = (await client.get("/api/today", headers=h)).json()
    assert today_data["summary"]["total"] == 2


async def test_auto_plan_empty_when_no_tasks(client):
    h = await _auth(client)
    r = await client.post("/api/today/auto-plan", headers=h)
    assert r.json()["created"] == []


async def test_manual_action_without_minutes(client):
    h = await _auth(client)
    r = await client.post(
        "/api/actions", json={"title": "7点起床", "minutes": 0, "date": dt.date.today().isoformat()}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["minutes"] == 0
    today_data = (await client.get("/api/today", headers=h)).json()
    assert today_data["summary"]["total"] == 1


async def test_delete_action(client):
    h = await _auth(client)
    today = dt.date.today().isoformat()
    a = (await client.post(
        "/api/actions", json={"title": "临时待办", "minutes": 0, "date": today}, headers=h
    )).json()
    r = await client.delete(f"/api/actions/{a['id']}", headers=h)
    assert r.json()["ok"] is True
    today_data = (await client.get("/api/today", headers=h)).json()
    assert today_data["summary"]["total"] == 0


async def test_daily_autoplan_runs_once(client):
    h = await _auth(client)
    await client.post("/api/tasks", json={"granularity": "week", "title": "T"}, headers=h)
    # manual run
    r1 = await client.post("/api/today/auto-plan", headers=h)
    assert len(r1.json()["created"]) == 1
    # lazy path: today view must not generate again (log exists)
    r2 = await client.get("/api/today", headers=h)
    assert r2.json()["summary"]["total"] == 1

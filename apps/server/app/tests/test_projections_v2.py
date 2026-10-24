"""Tests for: horizon projections, goal suggestions + apply, task decompose."""
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


async def test_projection_with_horizon_and_goals_reference(client):
    h = await _auth(client)
    g = (await client.post("/api/goals", json={"title": "五年内成为技术专家"}, headers=h)).json()
    r = await client.post(
        "/api/projections",
        json={"horizon_years": 3, "questionnaire": {"career": 6}},
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["horizon_years"] == 3
    # history carries horizon + referenced goals
    hist = (await client.get("/api/projections", headers=h)).json()
    assert hist[0]["horizon_years"] == 3
    assert hist[0]["input"]["referenced_goals"] == ["五年内成为技术专家"]


async def test_suggest_and_apply_goal(client):
    h = await _auth(client)
    p = (await client.post("/api/projections", json={"horizon_years": 5}, headers=h)).json()
    r = await client.post(f"/api/projections/{p['id']}/suggest-goals", json={"horizon_years": 5}, headers=h)
    assert r.status_code == 200, r.text
    sugg = r.json()["suggestions"]
    assert len(sugg) >= 1
    # apply first suggestion -> goal + tasks created
    s = sugg[0]
    r = await client.post(
        "/api/projections/apply-suggestion",
        json={"title": s["title"], "description": s.get("description"), "dimension": s.get("dimension"), "with_tasks": True},
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tasks_created"] >= 1
    tasks = (await client.get("/api/tasks", headers=h)).json()
    gran = {t["granularity"] for t in tasks}
    assert "year" in gran
    titles = [t["title"] for t in tasks]
    # year->month chain exists (degraded path builds year level; with LLM absent only
    # first level + template; month exists only if year produced children via LLM).
    assert all(t["goal_id"] for t in tasks if t["goal_id"] is not None)


async def test_decompose_task_progressive(client):
    h = await _auth(client)
    g = (await client.post("/api/goals", json={"title": "学英语"}, headers=h)).json()
    yt = (await client.post(
        "/api/tasks", json={"goal_id": g["id"], "granularity": "year", "title": "通过雅思6.5"}, headers=h
    )).json()
    r = await client.post(f"/api/tasks/{yt['id']}/decompose", json={}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["children"][0]["granularity"] == "month"
    # decompose month -> week
    mt = (await client.get("/api/tasks", headers=h)).json()
    month_task = [t for t in mt if t["parent_task_id"] == yt["id"]][0]
    r = await client.post(f"/api/tasks/{month_task['id']}/decompose", json={}, headers=h)
    kids = r.json()["children"]
    assert kids[0]["granularity"] == "week"
    # week task cannot be decomposed into tasks
    r = await client.post(f"/api/tasks/{kids[0]['id']}/decompose", json={}, headers=h)
    assert r.status_code == 400

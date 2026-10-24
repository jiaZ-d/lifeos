"""Timeline feature tests: period grouping, report generate/edit persistence."""
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


async def test_timeline_day_view_groups(client):
    h = await _auth(client)
    today = dt.date.today()
    await client.post("/api/entries", json={"categories": ["study"], "title": "读书"}, headers=h)
    await client.post("/api/entries", json={"categories": ["exercise"], "content": "跑步"}, headers=h)
    a = (await client.post(
        "/api/actions",
        json={"title": "今日待办甲", "minutes": 30, "date": today.isoformat()},
        headers=h,
    )).json()
    await client.post(f"/api/actions/{a['id']}/complete", headers=h)
    r = await client.get(f"/api/timeline?view=day&date={today.isoformat()}", headers=h)
    data = r.json()
    assert data["view"] == "day"
    assert len(data["periods"]) == 14
    # current period centered in the strip (需求: 当天显示在正中)
    idx = [i for i, p in enumerate(data["periods"]) if p["current"]][0]
    assert idx == 7  # 14 periods, current at index 7
    # strip counts are real across the whole strip
    today_p = data["periods"][idx]
    assert today_p["count"] == 2
    assert len(data["entries"]) == 2
    # day view links todos
    assert len(data["todos"]) == 1
    assert data["todos"][0]["title"] == "今日待办甲"
    assert data["todos"][0]["status"] == "done"
    assert data["prev"] and data["next"]


async def test_timeline_week_month_year(client):
    h = await _auth(client)
    for view in ("week", "month", "year"):
        r = await client.get(f"/api/timeline?view={view}", headers=h)
        data = r.json()
        assert data["period_key"]
        assert len(data["periods"]) >= 5
        assert "entries" in data


async def test_report_generate_edit_persistence(client):
    h = await _auth(client)
    today = dt.date.today()
    iso = today.isocalendar()
    week_key = f"{iso[0]}-W{iso[1]:02d}"
    # generate (no API key -> degraded template)
    r = await client.post(
        "/api/timeline/reports/generate",
        json={"period_type": "week", "period_key": week_key},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["degraded"] is True
    # user edits -> persisted, ai_generated flag flips
    r = await client.put(
        f"/api/timeline/reports/week/{week_key}",
        json={"content_md": "# 我的周报\n\n手动修改过的内容"},
        headers=h,
    )
    assert r.json()["ai_generated"] is False
    r = await client.get(f"/api/timeline/reports/week/{week_key}", headers=h)
    assert r.json()["exists"] is True
    assert "手动修改" in r.json()["content_md"]
    # month report as well
    month_key = today.strftime("%Y-%m")
    r = await client.post(
        "/api/timeline/reports/generate",
        json={"period_type": "month", "period_key": month_key},
        headers=h,
    )
    assert r.status_code == 200
    # invalid period type rejected
    r = await client.put(
        f"/api/timeline/reports/day/{today.isoformat()}", json={"content_md": "x"}, headers=h
    )
    assert r.status_code == 400

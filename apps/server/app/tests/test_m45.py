"""M4/M5 tests: projection (cold start + degraded fallback), stats, backup export/import."""
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
    import app.config as appcfg

    db_path = test_dir / "test.db"
    monkeypatch.setenv("LIFEOS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setattr(appcfg.settings, "database_url", f"sqlite+aiosqlite:///{db_path}", raising=False)
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    appdb.engine = eng
    appdb.SessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, db_path
    await eng.dispose()
    import shutil

    shutil.rmtree(test_dir, ignore_errors=True)


async def _auth(client):
    r = await client.post(
        "/api/auth/register", json={"username": f"u{uuid.uuid4().hex[:6]}", "password": "pass123456"}
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_projection_degraded_and_cold_start(client, monkeypatch):
    client_, _ = client
    h = await _auth(client_)
    # no API key -> LLMUnavailable -> degraded template report
    r = await client_.post("/api/projections", json={"questionnaire": {"health": 6}, "industry": "互联网"}, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["degraded"] is True
    assert data["cold_start"] is True  # no entries
    assert data["disclaimer"].startswith("AI 生成")
    assert "health_baseline" in data
    # history list
    r = await client_.get("/api/projections", headers=h)
    assert len(r.json()) == 1


async def test_health_baseline_rules(client):
    client_, _ = client
    h = await _auth(client_)
    # add exercise entries with extra fields
    for _ in range(4):
        await client_.post(
            "/api/entries",
            json={"categories": ["exercise"], "content": "跑步",
                  "extra_json": {"minutes": 40, "intensity": "high"}, "ai_allowed": False},
            headers=h,
        )
    r = await client_.post("/api/projections", json={}, headers=h)
    hb = r.json()["health_baseline"]
    assert hb["sample_size"] == 4
    assert 1.0 <= hb["score"] <= 10.0


async def test_stats_and_backup(client, monkeypatch):
    client_, db_path = client
    h = await _auth(client_)
    import app.config as appcfg
    monkeypatch.setattr(appcfg.settings, "database_url", f"sqlite+aiosqlite:///{db_path}", raising=False)
    today = dt.date.today().isoformat()
    a = (await client_.post("/api/actions", json={"title": "x", "minutes": 30, "date": today}, headers=h)).json()
    await client_.post(f"/api/actions/{a['id']}/complete", headers=h)
    r = await client_.get("/api/stats/heatmap", headers=h)
    assert sum(r.json()["actions"].values()) >= 1
    r = await client_.get("/api/stats/trend", headers=h)
    data = r.json()
    assert "series" in data and "summary" in data
    assert data["summary"]["done"] >= 1
    assert set(data["series"][0].keys()) == {"date", "planned", "done", "rate"}
    r = await client_.get("/api/stats/procrastination", headers=h)
    assert set(r.json().keys()) == {"debt", "given_up", "avg_postpone_count"}
    r = await client_.get("/api/stats/weekly-report", headers=h)
    assert "report" in r.json()
    # export: user-scoped snapshot, response returns NAME only (BUG-02)
    r = await client_.post("/api/stats/export", headers=h)
    assert r.status_code == 200, r.text
    name = r.json()["file"]
    assert "/" not in name and "\\" not in name  # no absolute path leak
    from pathlib import Path

    import app.config as appcfg2
    snap = Path(appcfg2.DATA_DIR) / "backups" / name
    assert snap.exists()
    import sqlite3 as s3

    conn = s3.connect(str(snap))
    users_in_snap = [u[0] for u in conn.execute("SELECT username FROM users").fetchall()]
    actions_in_snap = conn.execute("SELECT COUNT(*) FROM actions WHERE status='done'").fetchone()[0]
    conn.close()
    assert len(users_in_snap) == 1  # only the exporting user's row
    assert actions_in_snap >= 1  # user's completed actions copied


async def test_daily_summary_fallback(client):
    client_, _ = client
    h = await _auth(client_)
    r = await client_.post("/api/llm/daily-summary", json={}, headers=h)
    assert r.status_code == 200
    assert "summary" in r.json()


async def test_generate_tasks_fallback(client):
    client_, _ = client
    h = await _auth(client_)
    g = (await client_.post("/api/goals", json={"title": "学英语"}, headers=h)).json()
    r = await client_.post("/api/llm/generate-tasks", json={"goal_id": g["id"], "granularity": "week"}, headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["degraded"] is True  # no API key configured
    assert len(data["tasks"]) >= 2

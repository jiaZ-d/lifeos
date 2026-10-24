"""P1 remediation tests: scheduler jobs, summary edit, import conflicts, admin grant, lockout."""
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
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    appdb.engine = eng
    appdb.SessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(appcfg.settings, "database_url", f"sqlite+aiosqlite:///{db_path}", raising=False)
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


# ---------- P1-6: due_jobs / run_daily_jobs ----------

def test_due_jobs_schedule():
    from app.main import due_jobs

    assert due_jobs(dt.datetime(2026, 10, 23, 1, 0)) == ["prev_summary"]
    assert due_jobs(dt.datetime(2026, 10, 23, 2, 0)) == ["auto_plan"]
    assert due_jobs(dt.datetime(2026, 10, 23, 21, 30)) == ["today_summary"]
    assert due_jobs(dt.datetime(2026, 10, 23, 12, 0)) == []
    assert due_jobs(dt.datetime(2026, 10, 23, 2, 1)) == []  # 1-minute window only


async def test_run_daily_jobs_auto_plan(client):
    h = await _auth(client)
    await client.post("/api/tasks", json={"granularity": "week", "title": "T"}, headers=h)
    from app.main import run_daily_jobs

    ran = await run_daily_jobs(dt.datetime(2026, 10, 23, 2, 0))
    assert ran["auto_plan"]  # user got a planned action
    ran2 = await run_daily_jobs(dt.datetime(2026, 10, 23, 2, 0))
    assert ran2.get("auto_plan", []) == []  # auto-plan log prevents duplicates


async def test_run_daily_jobs_prev_summary(client):
    h = await _auth(client)
    from app.main import run_daily_jobs

    now = dt.datetime(2026, 10, 23, 1, 0)
    ran = await run_daily_jobs(now)
    assert ran["prev_summary"]
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import DailySummary

    async with SessionLocal() as db:
        rows = (await db.execute(select(DailySummary))).scalars().all()
        assert len(rows) == 1


# ---------- P1-2: summary edit ----------

async def test_daily_summary_edit(client):
    h = await _auth(client)
    day = dt.date.today().isoformat()
    r = await client.put(f"/api/llm/daily-summary/{day}", json={"content_md": "# 手工小结"}, headers=h)
    assert r.json()["ai_generated"] is False
    g = await client.get(f"/api/llm/daily-summary?date={day}", headers=h)
    assert g.json()["exists"] is True and g.json()["summary"] == "# 手工小结"


# ---------- P1-3: import conflict ----------

async def test_import_backup_conflicts(client, monkeypatch):
    h = await _auth(client)
    import app.config as appcfg

    # export uses the live settings path; rebind after fixture rebind
    exp = await client.post("/api/stats/export", headers=h)
    assert exp.status_code == 200, exp.text
    backup = str(appcfg.DATA_DIR / "backups" / exp.json()["file"])
    # wipe entries then import the backup -> should re-import
    entries = (await client.get("/api/entries", headers=h)).json()
    for e in entries:
        await client.delete(f"/api/entries/{e['id']}", headers=h)
    with open(backup, "rb") as f:
        r = await client.post(
            "/api/stats/import?conflict=skip",
            headers=h,
            files={"file": ("b.db", f, "application/octet-stream")},
        )
    assert r.status_code == 200, r.text
    after = (await client.get("/api/entries", headers=h)).json()
    assert all(e["title"] == "A" or e["title"] is None for e in after)


# ---------- P1-4: admin grant/revoke ----------

async def test_admin_grant_revoke_guards(client):
    admin = await client.post("/api/auth/register", json={"username": "root", "password": "pass123456"})
    ah = {"Authorization": f"Bearer {admin.json()['token']}"}
    bob = await client.post("/api/auth/register", json={"username": "bob2", "password": "pass123456"})
    bh = {"Authorization": f"Bearer {bob.json()['token']}"}
    bid = bob.json()["user_id"]
    aid = admin.json()["user_id"]
    assert (await client.get("/api/auth/users", headers=bh)).status_code == 403
    r = await client.put(f"/api/auth/users/{bid}/admin", json={"is_admin": True}, headers=ah)
    assert r.json()["is_admin"] is True
    r = await client.put(f"/api/auth/users/{aid}/admin", json={"is_admin": False}, headers=ah)
    assert r.status_code == 400  # cannot modify self
    r = await client.put(f"/api/auth/users/{bid}/admin", json={"is_admin": False}, headers=ah)
    assert r.json()["is_admin"] is False  # grant ok (root remains admin)
    r = await client.put(f"/api/auth/users/{aid}/admin", json={"is_admin": False}, headers=ah)
    assert r.status_code == 400  # cannot revoke the last admin


# ---------- P1-5: lockout ----------

async def test_pin_lockout(client):
    h = await _auth(client)
    await client.post("/api/auth/pin/setup", json={"pin": "abcdef"}, headers=h)
    for _ in range(5):
        r = await client.post("/api/auth/pin/verify", json={"pin": "000000"}, headers=h)
        assert r.status_code == 401
    r = await client.post("/api/auth/pin/verify", json={"pin": "abcdef"}, headers=h)
    assert r.status_code == 429  # locked even with correct PIN


# ---------- BUG-01: recovery-wrap is admin-only ----------

async def test_recovery_wrap_admin_only(client):
    # alice 是该测试库的首个用户 = 管理员,自己操作自己应允许
    alice = await client.post("/api/auth/register", json={"username": "alice9", "password": "pass123456"})
    ah = {"Authorization": f"Bearer {alice.json()['token']}"}
    assert alice.json()["is_admin"] is True
    await client.post("/api/auth/pin/setup", json={"pin": "abcdef"}, headers=ah)
    body = {"pin": "abcdef", "recovery_passphrase": "recovery-phrase-9"}
    r = await client.post("/api/auth/pin/recovery-wrap", json=body, headers=ah)
    assert r.status_code == 200, r.text
    # 新注册普通用户 bob:POST/DELETE 均应 403(BUG-01 越权修复)
    bob = await client.post("/api/auth/register", json={"username": "bob9", "password": "pass123456"})
    bh = {"Authorization": f"Bearer {bob.json()['token']}"}
    assert bob.json()["is_admin"] is False
    await client.post("/api/auth/pin/setup", json={"pin": "123456"}, headers=bh)
    r = await client.post("/api/auth/pin/recovery-wrap", json={"pin": "123456", "recovery_passphrase": "recovery-phrase-x"}, headers=bh)
    assert r.status_code == 403, r.text
    r = await client.delete("/api/auth/pin/recovery-wrap", headers=bh)
    assert r.status_code == 403


# ---------- BUG-02: export is user-scoped ----------

async def test_export_excludes_other_users(client):
    u1 = await client.post("/api/auth/register", json={"username": "exp1", "password": "pass123456"})
    h1 = {"Authorization": f"Bearer {u1.json()['token']}"}
    u2 = await client.post("/api/auth/register", json={"username": "exp2", "password": "pass123456"})
    h2 = {"Authorization": f"Bearer {u2.json()['token']}"}
    await client.post("/api/entries", json={"categories": ["study"], "title": "mine"}, headers=h1)
    await client.post("/api/entries", json={"categories": ["study"], "title": "theirs"}, headers=h2)
    r = await client.post("/api/stats/export", headers=h1)
    name = r.json()["file"]
    assert "/" not in name and "\\" not in name  # 无绝对路径泄露
    import sqlite3 as s3

    from app.config import DATA_DIR

    conn = s3.connect(str(DATA_DIR / "backups" / name))
    titles = [t[0] for t in conn.execute("SELECT title FROM entries").fetchall()]
    users = [u[0] for u in conn.execute("SELECT username FROM users").fetchall()]
    conn.close()
    assert "mine" in titles and "theirs" not in titles
    assert users == ["exp1"]

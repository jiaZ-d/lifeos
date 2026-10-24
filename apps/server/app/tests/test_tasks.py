"""M2 tests: goals -> tasks (year/month/week) -> actions, rollover/debt, board."""
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
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}"}


async def test_goal_task_action_flow(client):
    h = await _auth(client)
    g = (await client.post("/api/goals", json={"title": "十年成长", "dimension": "growth"}, headers=h)).json()
    yt = (await client.post(
        "/api/tasks",
        json={"goal_id": g["id"], "granularity": "year", "title": "通过 PMP"},
        headers=h,
    )).json()
    mt = (await client.post(
        "/api/tasks",
        json={"parent_task_id": yt["id"], "granularity": "month", "title": "完成前五章"},
        headers=h,
    )).json()
    # wrong granularity rejected
    r = await client.post(
        "/api/tasks", json={"parent_task_id": mt["id"], "granularity": "year", "title": "bad"}, headers=h
    )
    assert r.status_code == 400
    a = (await client.post(
        "/api/actions",
        json={"task_id": mt["id"], "title": "读书30分钟", "minutes": 30, "date": dt.date.today().isoformat()},
        headers=h,
    )).json()
    r = await client.post(f"/api/actions/{a['id']}/complete", headers=h)
    assert r.json()["status"] == "done"
    assert r.json()["done_at"] is not None
    # undo -> open again (no log, P0-3)
    r = await client.post(f"/api/actions/{a['id']}/reopen", headers=h)
    assert r.json()["status"] == "open" and r.json()["done_at"] is None
    # task progress = action completion
    tasks = (await client.get("/api/tasks", headers=h)).json()
    prog = {t["id"]: t["progress"] for t in tasks}
    assert prog[mt["id"]] == 0.0
    await client.post(f"/api/actions/{a['id']}/complete", headers=h)
    tasks = (await client.get("/api/tasks", headers=h)).json()
    prog = {t["id"]: t["progress"] for t in tasks}
    assert prog[mt["id"]] == 1.0
    # goal progress computed read-only
    goals = (await client.get("/api/goals", headers=h)).json()
    assert goals[0]["progress"] > 0


async def test_rollover_and_debt(client, monkeypatch):
    h = await _auth(client)
    today = dt.date.today()
    # create an action dated 3 days ago (already overdue)
    a = (await client.post(
        "/api/actions",
        json={"title": "拖延的事", "minutes": 20, "date": (today - dt.timedelta(days=3)).isoformat()},
        headers=h,
    )).json()
    # directly set postpone_count to 2 so one rollover triggers debt
    import app.db as appdb
    from sqlalchemy import update
    from app.models import Action

    async with appdb.SessionLocal() as db:
        await db.execute(update(Action).where(Action.id == a["id"]).values(postpone_count=2, date=today - dt.timedelta(days=1)))
        await db.commit()
    r = await client.get("/api/today", headers=h)
    data = r.json()
    assert len(data["debts"]) == 1
    assert data["debts"][0]["status"] == "debt"
    debt_id = data["debts"][0]["id"]
    # do-today resets it
    r = await client.post(f"/api/actions/{debt_id}/debt/do", headers=h)
    assert r.json()["status"] == "open" and r.json()["postpone_count"] == 0
    # give up path
    async with appdb.SessionLocal() as db:
        await db.execute(update(Action).where(Action.id == a["id"]).values(postpone_count=3, status="debt"))
        await db.commit()
    r = await client.post(f"/api/actions/{a['id']}/debt/giveup", headers=h)
    assert r.json()["status"] == "given_up"


async def test_board_columns(client):
    h = await _auth(client)
    t1 = (await client.post("/api/tasks", json={"granularity": "week", "title": "A"}, headers=h)).json()
    t2 = (await client.post("/api/tasks", json={"granularity": "week", "title": "B"}, headers=h)).json()
    await client.put(f"/api/tasks/{t2['id']}", json={"status": "doing"}, headers=h)
    b = (await client.get("/api/board?dimension=week", headers=h)).json()
    assert [c["id"] for c in b["columns"]["backlog"]] == [t1["id"]]
    assert [c["id"] for c in b["columns"]["doing"]] == [t2["id"]]
    assert b["columns"]["done"] == []
    # granularity filter
    b2 = (await client.get("/api/board?dimension=month", headers=h)).json()
    assert all(not col for col in b2["columns"].values())


async def test_board_goal_status_derived(client):
    h = await _auth(client)
    g = (await client.post("/api/goals", json={"title": "推导目标"}, headers=h)).json()
    sub = (await client.post(
        "/api/tasks", json={"goal_id": g["id"], "granularity": "year", "title": "子目标1"}, headers=h
    )).json()
    mt = (await client.post(
        "/api/tasks", json={"parent_task_id": sub["id"], "granularity": "month", "title": "月规划1"}, headers=h
    )).json()
    a1 = (await client.post(
        "/api/actions", json={"task_id": mt["id"], "title": "act1", "minutes": 30,
                              "date": dt.date.today().isoformat()}, headers=h
    )).json()
    await client.post(
        "/api/actions", json={"task_id": mt["id"], "title": "act2", "minutes": 30,
                              "date": dt.date.today().isoformat()}, headers=h
    )
    b = (await client.get("/api/board?dimension=goal", headers=h)).json()
    assert b["dimension"] == "goal"
    card = [c for c in b["columns"]["backlog"] if c["id"] == g["id"]]
    assert card and card[0]["derived"] is True
    # complete one of two actions -> month doing -> sub doing -> goal doing
    await client.post(f"/api/actions/{a1['id']}/complete", headers=h)
    b = (await client.get("/api/board?dimension=goal", headers=h)).json()
    assert [c["id"] for c in b["columns"]["doing"]] == [g["id"]]
    # mark month done manually -> sub done -> goal done
    await client.put(f"/api/tasks/{mt['id']}", json={"status": "done"}, headers=h)
    b = (await client.get("/api/board?dimension=goal", headers=h)).json()
    assert [c["id"] for c in b["columns"]["done"]] == [g["id"]]


async def test_board_sub_dimension_derived(client):
    h = await _auth(client)
    g = (await client.post("/api/goals", json={"title": "g"}, headers=h)).json()
    sub = (await client.post(
        "/api/tasks", json={"goal_id": g["id"], "granularity": "year", "title": "子目标"}, headers=h
    )).json()
    r = await client.post(f"/api/tasks/{sub['id']}/decompose", json={}, headers=h)
    children = r.json()["children"]
    # sub has children -> status derived (still backlog since no weeks started)
    tasks = (await client.get("/api/tasks", headers=h)).json()
    sub_t = [t for t in tasks if t["id"] == sub["id"]][0]
    # complete the month child -> derived doing
    month_id = children[0]["id"]
    await client.put(f"/api/tasks/{month_id}", json={"status": "doing"}, headers=h)
    subs = (await client.get("/api/board?dimension=sub", headers=h)).json()
    card = [c for c in subs["columns"]["doing"] if c["id"] == sub["id"]]
    assert card and card[0]["derived_status"] == "doing"

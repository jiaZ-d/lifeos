"""API smoke tests: register/login/entry CRUD with private encryption + scope rules."""
import shutil
import uuid
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select as sa_select

from app.main import app

_RUN_TMP = Path(__file__).resolve().parents[3] / ".tmp-run"


@pytest.fixture
async def client(monkeypatch):
    test_dir = _RUN_TMP / uuid.uuid4().hex[:8]
    test_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LIFEOS_DATABASE_URL", f"sqlite+aiosqlite:///{test_dir}/test.db")
    # rebind engine to test db
    import app.db as appdb
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    eng = create_async_engine(f"sqlite+aiosqlite:///{test_dir}/test.db")
    appdb.engine = eng
    appdb.SessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    await eng.dispose()
    shutil.rmtree(test_dir, ignore_errors=True)


async def _register(client: AsyncClient, username="alice"):
    r = await client.post("/api/auth/register", json={"username": username, "password": "pass123456"})
    assert r.status_code == 200, r.text
    return r.json()


async def _setup_pin(client: AsyncClient, token: str, pin="abcdef"):
    r = await client.post(
        "/api/auth/pin/setup", json={"pin": pin}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text


async def test_health(client):
    r = await client.get("/api/health")
    assert r.json()["status"] == "ok"


async def test_register_login(client):
    await _register(client)
    r = await client.post("/api/auth/login", json={"username": "alice", "password": "pass123456"})
    assert r.status_code == 200
    r = await client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert r.status_code == 401


async def test_first_user_is_admin(client):
    data = await _register(client)
    assert data["is_admin"] is True
    data2 = await _register(client, "bob")
    assert data2["is_admin"] is False


async def test_entry_crud_and_categories(client):
    t = (await _register(client))["token"]
    h = {"Authorization": f"Bearer {t}"}
    r = await client.post(
        "/api/entries",
        json={"categories": ["study", "work"], "title": "复习", "content": "PMP 第五章", "tags": ["pmp"]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["primary_category"] == "study"
    assert sorted(e["categories"]) == ["study", "work"]
    r = await client.get("/api/entries?category=work", headers=h)
    # primary-category scope: entry counts under study only (P0-2)
    assert all(x["primary_category"] == "study" for x in r.json())
    r = await client.put(f"/api/entries/{e['id']}", json={"content": "改了"}, headers=h)
    assert r.json()["content"] == "改了"
    r = await client.delete(f"/api/entries/{e['id']}", headers=h)
    assert r.json()["ok"]


async def test_private_entry_encrypted_at_rest(client):
    t = (await _register(client))["token"]
    h = {"Authorization": f"Bearer {t}"}
    await _setup_pin(client, t)
    r = await client.post(
        "/api/entries",
        json={"categories": ["social"], "title": "私密日记", "content": "不想被看到", "is_private": True, "pin": "abcdef"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["title"] is None and e["content"] is None  # plaintext nulled (clarify-3)
    # unlock with correct pin
    r = await client.get(f"/api/entries/unlock/{e['id']}?pin=abcdef", headers=h)
    assert r.json()["content"] == "不想被看到"
    # wrong pin
    r = await client.get(f"/api/entries/unlock/{e['id']}?pin=000000", headers=h)
    assert r.status_code == 401


async def test_search_excludes_private(client):
    t = (await _register(client))["token"]
    h = {"Authorization": f"Bearer {t}"}
    await _setup_pin(client, t)
    await client.post(
        "/api/entries", json={"categories": ["study"], "title": "公开笔记内容xyz", "content": "hello world"}, headers=h
    )
    await client.post(
        "/api/entries",
        json={"categories": ["study"], "title": "秘密内容abc", "content": "隐藏的", "is_private": True, "pin": "abcdef"},
        headers=h,
    )
    r = await client.get("/api/entries/search?q=公开笔记", headers=h)
    assert len(r.json()["results"]) == 1
    r = await client.get("/api/entries/search?q=秘密内容", headers=h)
    assert r.json()["results"] == []  # private not in FTS
    # in-session decrypted search (clarify-5)
    r = await client.get("/api/entries/search?q=秘密内容&pin=abcdef", headers=h)
    assert len(r.json()["private_hits"]) == 1


async def test_scope_ai_intersection(client, monkeypatch):
    from app.services import scope
    import app.db as appdb

    t = (await _register(client))["token"]
    h = {"Authorization": f"Bearer {t}"}
    # social default excluded
    await client.post("/api/entries", json={"categories": ["social"], "content": "s1"}, headers=h)
    await client.post("/api/entries", json={"categories": ["study"], "content": "s2"}, headers=h)
    await client.post(
        "/api/entries", json={"categories": ["work"], "content": "s3", "ai_allowed": False}, headers=h
    )
    from app.db import SessionLocal
    from app.models import User

    async with SessionLocal() as db:
        uid = (await db.execute(sa_select(User).where(User.username == "alice"))).scalar_one().id
        entries = await scope.ai_visible_entries(db, uid)
        contents = sorted(e.content for e in entries)
    assert contents == ["s2"]


async def test_admin_pin_recovery(client):
    t = (await _register(client))["token"]  # first user = admin
    h = {"Authorization": f"Bearer {t}"}
    await _setup_pin(client, t, "abcdef")
    r = await client.post(
        "/api/auth/pin/recovery-wrap", json={"pin": "abcdef", "recovery_passphrase": "recovery-phrase-1"}, headers=h
    )
    assert r.status_code == 200, r.text
    # forgot pin -> recover with admin creds + passphrase
    r = await client.post(
        "/api/auth/pin/recover/alice",
        json={
            "username": "alice",
            "admin_password": "pass123456",
            "recovery_passphrase": "recovery-phrase-1",
            "new_pin": "newpin66",
        },
    )
    assert r.status_code == 200, r.text
    # old private data still readable with new pin
    r = await client.post(
        "/api/entries",
        json={"categories": ["diet"], "content": "午餐沙拉", "is_private": True, "pin": "newpin66"},
        headers=h,
    )
    assert r.status_code == 200


async def test_privacy_settings(client):
    t = (await _register(client))["token"]
    h = {"Authorization": f"Bearer {t}"}
    r = await client.put(
        "/api/entries/privacy", json={"category": "social", "ai_allowed": True}, headers=h
    )
    assert r.status_code == 200
    r = await client.get("/api/entries/privacy", headers=h)
    assert r.json()[0]["category"] == "social"

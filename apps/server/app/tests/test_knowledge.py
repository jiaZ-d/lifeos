"""Knowledge base: domain/folder/note CRUD, cross-user isolation, image upload."""
import uuid
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app

_RUN_TMP = Path(__file__).resolve().parents[3] / ".tmp-run"


@pytest.fixture
async def client(monkeypatch, tmp_path):
    test_dir = _RUN_TMP / uuid.uuid4().hex[:8]
    test_dir.mkdir(parents=True, exist_ok=True)
    import app.db as appdb
    import app.config as appcfg
    import app.api.knowledge as kb

    db_path = test_dir / "test.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    appdb.engine = eng
    appdb.SessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr(appcfg.settings, "database_url", f"sqlite+aiosqlite:///{db_path}", raising=False)
    # keep test images out of the real data/files dir
    monkeypatch.setattr(kb, "KNOWLEDGE_DIR", tmp_path / "kb-images")
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    await eng.dispose()

    import shutil

    shutil.rmtree(test_dir, ignore_errors=True)


async def _auth(client, username=None):
    r = await client.post(
        "/api/auth/register",
        json={"username": username or f"kb{uuid.uuid4().hex[:6]}", "password": "pass123456"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user_id"]


async def test_knowledge_crud_flow(client):
    h, _ = await _auth(client, "kbowner")
    # duplicate domain name -> 409
    await client.post("/api/knowledge/domains", json={"name": "前端"}, headers=h)
    assert (await client.post("/api/knowledge/domains", json={"name": "前端"}, headers=h)).status_code == 409
    d = (await client.post("/api/knowledge/domains", json={"name": "健康"}, headers=h)).json()
    f = (await client.post(f"/api/knowledge/domains/{d['id']}/folders", json={"name": "睡眠"}, headers=h)).json()
    n = (
        await client.post(
            "/api/knowledge/notes",
            json={"folder_id": f["id"], "title": "第一篇", "content_md": "# hi\n\n![](img.png)"},
            headers=h,
        )
    ).json()

    tree = await client.get("/api/knowledge/tree", headers=h)
    assert tree.status_code == 200
    t = {x["name"]: x for x in tree.json()}
    assert set(t) == {"前端", "健康"}
    assert [fo["name"] for fo in t["健康"]["folders"]] == ["睡眠"]
    assert [no["title"] for no in t["健康"]["folders"][0]["notes"]] == ["第一篇"]

    got = await client.get(f"/api/knowledge/notes/{n['id']}", headers=h)
    assert got.json()["content_md"].startswith("# hi")

    upd = await client.put(f"/api/knowledge/notes/{n['id']}", json={"title": "改名"}, headers=h)
    assert upd.status_code == 200
    assert (await client.get(f"/api/knowledge/notes/{n['id']}", headers=h)).json()["title"] == "改名"

    # cascade 1: delete the DOMAIN while folder+note still inside (FK-safe order)
    assert (await client.delete(f"/api/knowledge/domains/{d['id']}", headers=h)).status_code == 200
    assert (await client.get(f"/api/knowledge/notes/{n['id']}", headers=h)).status_code == 404

    # cascade 2: delete a FOLDER with a note inside
    fed = (await client.get("/api/knowledge/tree", headers=h)).json()
    fe_id = fed[0]["id"]  # remaining "前端" domain
    f2 = (await client.post(f"/api/knowledge/domains/{fe_id}/folders", json={"name": "F2"}, headers=h)).json()
    n2 = (await client.post("/api/knowledge/notes", json={"folder_id": f2["id"], "title": "N2"}, headers=h)).json()
    await client.delete(f"/api/knowledge/folders/{f2['id']}", headers=h)
    assert (await client.get(f"/api/knowledge/notes/{n2['id']}", headers=h)).status_code == 404


async def test_knowledge_user_isolation(client):
    h1, _ = await _auth(client, "kbuser1")
    h2, _ = await _auth(client, "kbuser2")
    d = (await client.post("/api/knowledge/domains", json={"name": "私有"}, headers=h1)).json()
    f = (await client.post(f"/api/knowledge/domains/{d['id']}/folders", json={"name": "F"}, headers=h1)).json()
    n = (await client.post("/api/knowledge/notes", json={"folder_id": f["id"], "title": "N"}, headers=h1)).json()

    assert (await client.get("/api/knowledge/tree", headers=h2)).json() == []
    # note GET/PUT are real routes -> 404 via ownership filter
    assert (await client.get(f"/api/knowledge/notes/{n['id']}", headers=h2)).status_code == 404
    assert (await client.put(f"/api/knowledge/notes/{n['id']}", json={"title": "劫持"}, headers=h2)).status_code == 404
    # folder/domain have no GET route (SPA fallback would 200) -> probe with DELETE/POST
    assert (await client.delete(f"/api/knowledge/folders/{f['id']}", headers=h2)).status_code == 404
    assert (await client.delete(f"/api/knowledge/domains/{d['id']}", headers=h2)).status_code == 404
    # folder under someone else's domain -> 404
    assert (
        await client.post(f"/api/knowledge/domains/{d['id']}/folders", json={"name": "X"}, headers=h2)
    ).status_code == 404


async def test_knowledge_image_upload_and_access(client):
    h1, u1 = await _auth(client, "kbimg1")
    h2, u2 = await _auth(client, "kbimg2")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    r = await client.post(
        "/api/knowledge/upload-image", headers=h1, files={"file": ("shot.png", png, "image/png")}
    )
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith(f"/api/knowledge/images/{u1}/") and url.endswith(".png")

    ok = await client.get(url, headers=h1)
    assert ok.status_code == 200 and ok.content == png
    # other user's URL -> 403; owner token on a missing name -> 404
    assert (await client.get(url, headers=h2)).status_code == 403
    assert (await client.get(f"/api/knowledge/images/{u1}/nope.png", headers=h1)).status_code == 404
    # traversal-ish name: must never serve image content (404, or SPA fallback HTML)
    probe = await client.get(f"/api/knowledge/images/{u1}/..%2Fsecret", headers=h1)
    assert probe.status_code != 200 or "image" not in probe.headers.get("content-type", "")
    # non-image rejected
    bad = await client.post(
        "/api/knowledge/upload-image", headers=h1, files={"file": ("evil.exe", b"MZ", "application/x-msdownload")}
    )
    assert bad.status_code == 400

    # Cookie 兜底鉴权(Markdown 预览中的 <img> 无法携带 Authorization 头)
    r3 = await client.post("/api/auth/register", json={"username": "kbimg3", "password": "pass123456"})
    tok3 = r3.json()["token"]
    up3 = await client.post(
        "/api/knowledge/upload-image",
        headers={"Authorization": f"Bearer {tok3}"},
        files={"file": ("c.png", png, "image/png")},
    )
    url3 = up3.json()["url"]
    own = await client.get(url3, cookies={"lifeos_token": tok3})
    assert own.status_code == 200 and own.content == png  # 本人 cookie 可取
    assert (await client.get(url, cookies={"lifeos_token": tok3})).status_code == 403  # 他人图片仍拒绝
    assert (await client.get(url3)).status_code == 401  # 无任何凭据

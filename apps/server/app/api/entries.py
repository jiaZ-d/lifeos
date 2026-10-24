"""Entries: six-category journal CRUD, privacy encryption, FTS5 search (M1a/M1b)."""
from __future__ import annotations

import base64
import datetime as dt
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas
from ..auth import get_current_user
from ..db import get_db
from ..models import Entry, EntryCategory, PrivacySetting, User
from ..services import crypto

router = APIRouter(prefix="/api/entries", tags=["entries"])

PRIVATE_NULLABLE = ("title", "content", "mood", "tags", "extra_json")  # clarify-3


def _category_values(categories: list[str]) -> list[EntryCategory]:
    return [EntryCategory(c) for c in categories]


def _to_out(e: Entry) -> schemas.EntryOut:
    return schemas.EntryOut(
        id=e.id,
        categories=e.categories or [],
        primary_category=e.primary_category.value if e.primary_category else "",
        title=e.title,
        content=e.content,
        mood=e.mood,
        tags=e.tags,
        attachments=e.attachments,
        is_private=e.is_private,
        ai_allowed=e.ai_allowed,
        extra_json=e.extra_json,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


async def _ensure_fts(db: AsyncSession) -> None:
    await db.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5("
            "title, content, tags, tokenize='trigram')"
        )
    )


async def _fts_upsert(db: AsyncSession, entry_id: int, e: Entry) -> None:
    """Only non-private entries enter the index (design P1-2)."""
    await _ensure_fts(db)
    await db.execute(text("DELETE FROM entries_fts WHERE rowid = :i"), {"i": entry_id})
    if not e.is_private:
        await db.execute(
            text("INSERT INTO entries_fts(rowid, title, content, tags) VALUES (:i, :t, :c, :g)"),
            {
                "i": entry_id,
                "t": e.title or "",
                "c": e.content or "",
                "g": " ".join(e.tags or []),
            },
        )


@router.post("", response_model=schemas.EntryOut)
async def create_entry(
    body: schemas.EntryIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cats = _category_values(body.categories)
    dek = None
    if body.is_private:
        if not body.pin:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "pin required for private entries")
        keys = (
            await db.execute(
                text("SELECT * FROM user_keys WHERE user_id = :u"), {"u": user.id}
            )
        ).mappings().first()
        if keys is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set up PIN first (POST /api/auth/pin/setup)")
        dek = crypto.unwrap_dek(keys["wrapped_dek"], body.pin, keys["kek_salt"])
        if not crypto.verify_pin(body.pin, keys["pin_verify_salt"], keys["pin_verify_hash"]):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong PIN")

    payload = {
        "title": body.title,
        "content": body.content,
        "mood": body.mood,
        "tags": body.tags,
        "extra_json": body.extra_json,
    }
    encrypted_blob = None
    if body.is_private:
        encrypted_blob = crypto.encrypt_payload(dek, json.dumps(payload, ensure_ascii=False).encode())
        payload = {k: None for k in PRIVATE_NULLABLE}

    e = Entry(
        user_id=user.id,
        categories=body.categories,
        primary_category=cats[0],
        is_private=body.is_private,
        ai_allowed=body.ai_allowed,
        attachments=[],
        encrypted_blob=encrypted_blob,
        **payload,
    )
    db.add(e)
    await db.flush()
    await _fts_upsert(db, e.id, e)
    await db.commit()
    await db.refresh(e)
    return _to_out(e)


@router.get("", response_model=list[schemas.EntryOut])
async def list_entries(
    category: str | None = None,
    tag: str | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Timeline. Category filter uses primary_category (statistic scope, P0-2)."""
    q = select(Entry).where(Entry.user_id == user.id)
    if category:
        q = q.where(Entry.primary_category == EntryCategory(category))
    if tag:
        q = q.where(Entry.tags.contains([tag]))
    if start:
        q = q.where(Entry.created_at >= start)
    if end:
        q = q.where(Entry.created_at < end + dt.timedelta(days=1))
    q = q.order_by(Entry.created_at.desc()).limit(limit).offset(offset)
    return [_to_out(e) for e in (await db.execute(q)).scalars().all()]


@router.get("/search")
async def search_entries(
    q: str = Query(min_length=1),
    pin: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """FTS5 search (trigram, >=3 chars; shorter falls back to LIKE).
    Private entries are searched only in-session over decrypted set (clarify-5),
    which requires the PIN; otherwise they are skipped."""
    await _ensure_fts(db)
    ids: list[int] = []
    if len(q.strip()) >= 3:
        rows = await db.execute(
            text("SELECT rowid FROM entries_fts WHERE entries_fts MATCH :m"), {"m": q}
        )
        ids = [r[0] for r in rows]
    if not ids:
        like = f"%{q}%"
        rows = await db.execute(
            text(
                "SELECT id FROM entries WHERE user_id=:u AND is_private=0 "
                "AND (title LIKE :l OR content LIKE :l)"
            ),
            {"u": user.id, "l": like},
        )
        ids = [r[0] for r in rows]

    items = (
        await db.execute(
            select(Entry).where(Entry.id.in_(ids), Entry.user_id == user.id, Entry.is_private == False)  # noqa: E712
        )
    ).scalars().all()

    decrypted: list[dict] = []
    if pin:
        keys = (
            await db.execute(
                text("SELECT * FROM user_keys WHERE user_id = :u"), {"u": user.id}
            )
        ).mappings().first()
        if keys and crypto.verify_pin(pin, keys["pin_verify_salt"], keys["pin_verify_hash"]):
            dek = crypto.unwrap_dek(keys["wrapped_dek"], pin, keys["kek_salt"])
            priv = (
                await db.execute(
                    select(Entry).where(Entry.user_id == user.id, Entry.is_private == True)  # noqa: E712
                )
            ).scalars().all()
            for p in priv:
                try:
                    data = json.loads(crypto.decrypt_payload(dek, p.encrypted_blob))
                except Exception:
                    continue
                if q in (data.get("title") or "") or q in (data.get("content") or ""):
                    decrypted.append(
                        {
                            **_to_out(p).model_dump(mode="json"),
                            "title": data.get("title"),
                            "content": data.get("content"),
                            "mood": data.get("mood"),
                            "tags": data.get("tags"),
                            "extra_json": data.get("extra_json"),
                        }
                    )
    return {"results": [_to_out(e).model_dump(mode="json") for e in items], "private_hits": decrypted}


@router.get("/unlock/{entry_id}", response_model=schemas.EntryOut)
async def unlock_entry(
    entry_id: int,
    pin: str = Query(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    e = (
        await db.execute(select(Entry).where(Entry.id == entry_id, Entry.user_id == user.id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    if not e.is_private:
        return _to_out(e)
    keys = (
        await db.execute(text("SELECT * FROM user_keys WHERE user_id = :u"), {"u": user.id})
    ).mappings().first()
    if keys is None or not crypto.verify_pin(pin, keys["pin_verify_salt"], keys["pin_verify_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong PIN")
    dek = crypto.unwrap_dek(keys["wrapped_dek"], pin, keys["kek_salt"])
    data = json.loads(crypto.decrypt_payload(dek, e.encrypted_blob))
    out = _to_out(e).model_dump(mode="json")
    out.update({k: data.get(k) for k in PRIVATE_NULLABLE})
    return schemas.EntryOut(**out)


# ---------- attachments (P0-1) ----------

@router.post("/{entry_id}/attachments")
async def upload_attachment(
    entry_id: int,
    pin: str | None = Query(default=None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload an image/file to an entry. Private entries encrypt the file (P0-1)."""
    import uuid as _uuid

    from ..config import settings as cfg

    e = (
        await db.execute(select(Entry).where(Entry.id == entry_id, Entry.user_id == user.id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")

    raw = await file.read()
    stored_name = f"{_uuid.uuid4().hex}_{file.filename}"
    rel_dir = Path(cfg.files_dir) / str(user.id) / str(entry_id)
    rel_dir.mkdir(parents=True, exist_ok=True)
    out_path = rel_dir / stored_name

    if e.is_private:
        keys = (
            await db.execute(text("SELECT * FROM user_keys WHERE user_id = :u"), {"u": user.id})
        ).mappings().first()
        if keys is None or not crypto.verify_pin(pin or "", keys["pin_verify_salt"], keys["pin_verify_hash"]):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong PIN")
        dek = crypto.unwrap_dek(keys["wrapped_dek"], pin, keys["kek_salt"])
        out_path.write_bytes(_encrypt_bytes(dek, raw))
    else:
        out_path.write_bytes(raw)

    rel = f"{user.id}/{entry_id}/{stored_name}"
    e.attachments = list(e.attachments or []) + [rel]
    await db.commit()
    return {"ok": True, "path": rel, "name": file.filename}


def _encrypt_bytes(dek: bytes, data: bytes) -> bytes:
    return crypto.encrypt_payload(dek, data).encode()


@router.get("/{entry_id}/attachments/{index}")
async def download_attachment(
    entry_id: int,
    index: int,
    pin: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import FileResponse

    from ..config import settings as cfg

    e = (
        await db.execute(select(Entry).where(Entry.id == entry_id, Entry.user_id == user.id))
    ).scalar_one_or_none()
    if e is None or not e.attachments or index >= len(e.attachments):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    rel = e.attachments[index]
    path = Path(cfg.files_dir) / rel
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing")
    name = rel.split("/")[-1]
    if e.is_private:
        keys = (
            await db.execute(text("SELECT * FROM user_keys WHERE user_id = :u"), {"u": user.id})
        ).mappings().first()
        if keys is None or not pin or not crypto.verify_pin(pin, keys["pin_verify_salt"], keys["pin_verify_hash"]):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong PIN")
        dek = crypto.unwrap_dek(keys["wrapped_dek"], pin, keys["kek_salt"])
        data = crypto.decrypt_payload(dek, path.read_bytes().decode())
        return Response(
            content=base64.urlsafe_b64decode(data),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="file-{index}"'},
        )
    return FileResponse(path, filename=name)


# ---------- privacy settings (declared before /{entry_id} routes to avoid path conflicts) ----------

@router.get("/privacy", response_model=list[dict])
async def get_privacy(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    rows = (
        await db.execute(select(PrivacySetting).where(PrivacySetting.user_id == user.id))
    ).scalars().all()
    return [
        {
            "category": r.category.value,
            "visible": r.visible,
            "pin_required": r.pin_required,
            "ai_allowed": r.ai_allowed,
        }
        for r in rows
    ]


@router.put("/privacy")
async def set_privacy(
    body: schemas.PrivacyCategoryIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(PrivacySetting).where(
                PrivacySetting.user_id == user.id,
                PrivacySetting.category == EntryCategory(body.category),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = PrivacySetting(user_id=user.id, category=EntryCategory(body.category))
        db.add(row)
    if body.visible is not None:
        row.visible = body.visible
    if body.pin_required is not None:
        row.pin_required = body.pin_required
    if body.ai_allowed is not None:
        row.ai_allowed = body.ai_allowed
    await db.commit()
    return {"ok": True}


@router.put("/{entry_id}", response_model=schemas.EntryOut)
async def update_entry(
    entry_id: int,
    body: schemas.EntryUpdateIn,
    pin: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    e = (
        await db.execute(select(Entry).where(Entry.id == entry_id, Entry.user_id == user.id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")

    updates = body.model_dump(exclude_unset=True, exclude={"pin"})
    if e.is_private:
        if not pin:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "pin query param required for private entry")
        keys = (
            await db.execute(text("SELECT * FROM user_keys WHERE user_id = :u"), {"u": user.id})
        ).mappings().first()
        if keys is None or not crypto.verify_pin(pin, keys["pin_verify_salt"], keys["pin_verify_hash"]):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong PIN")
        dek = crypto.unwrap_dek(keys["wrapped_dek"], pin, keys["kek_salt"])
        data = json.loads(crypto.decrypt_payload(dek, e.encrypted_blob))
        for k in PRIVATE_NULLABLE:
            if k in updates:
                data[k] = updates.pop(k)
        e.encrypted_blob = crypto.encrypt_payload(dek, json.dumps(data, ensure_ascii=False).encode())
    for k, v in updates.items():
        setattr(e, k, v)
    if body.categories:
        e.primary_category = EntryCategory(body.categories[0])
    await db.flush()
    await _fts_upsert(db, e.id, e)
    await db.commit()
    await db.refresh(e)
    return _to_out(e)


@router.delete("/{entry_id}")
async def delete_entry(
    entry_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    e = (
        await db.execute(select(Entry).where(Entry.id == entry_id, Entry.user_id == user.id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    await _ensure_fts(db)
    await db.execute(text("DELETE FROM entries_fts WHERE rowid = :i"), {"i": entry_id})
    await db.delete(e)
    await db.commit()
    return {"ok": True}

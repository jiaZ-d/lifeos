"""个人知识库:领域/文件夹/笔记 CRUD + 图片上传与访问 (Markdown 嵌入)."""
from __future__ import annotations

import uuid as _uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, get_current_user_or_cookie
from ..config import settings
from ..db import get_db
from ..models import KnowledgeDomain, KnowledgeFolder, KnowledgeNote, User
from .tasks import _owned  # reuse ownership helper (task-agnostic by model)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class NoteIn(BaseModel):
    folder_id: int
    title: str = Field(min_length=1, max_length=256)
    content_md: str = ""


class NoteUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    content_md: str | None = None
    folder_id: int | None = None  # move note


# ---------- tree ----------

@router.get("/tree")
async def get_tree(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Full tree: domains -> folders -> notes(list meta only)."""
    domains = (
        await db.execute(
            select(KnowledgeDomain).where(KnowledgeDomain.user_id == user.id).order_by(KnowledgeDomain.id)
        )
    ).scalars().all()
    folders = (
        await db.execute(
            select(KnowledgeFolder).where(KnowledgeFolder.user_id == user.id).order_by(KnowledgeFolder.id)
        )
    ).scalars().all()
    notes = (
        await db.execute(
            select(KnowledgeNote).where(KnowledgeNote.user_id == user.id).order_by(KnowledgeNote.updated_at.desc())
        )
    ).scalars().all()
    notes_by_folder: dict[int, list] = {}
    for n in notes:
        notes_by_folder.setdefault(n.folder_id, []).append(
            {"id": n.id, "title": n.title, "updated_at": n.updated_at.isoformat()}
        )
    folders_by_domain: dict[int, list] = {}
    for f in folders:
        folders_by_domain.setdefault(f.domain_id, []).append(
            {"id": f.id, "name": f.name, "notes": notes_by_folder.get(f.id, [])}
        )
    return [
        {"id": d.id, "name": d.name, "folders": folders_by_domain.get(d.id, [])}
        for d in domains
    ]


# ---------- domain ----------

@router.post("/domains")
async def create_domain(
    body: NameIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    exists = (
        await db.execute(
            select(KnowledgeDomain).where(
                KnowledgeDomain.user_id == user.id, KnowledgeDomain.name == body.name
            )
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名领域已存在")
    d = KnowledgeDomain(user_id=user.id, name=body.name)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return {"id": d.id, "name": d.name}


@router.delete("/domains/{domain_id}")
async def delete_domain(
    domain_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Delete domain with all folders & notes (children first — raw FK has no
    ORM relationship, so unit-of-work ordering cannot be trusted here)."""
    d = await _owned(db, KnowledgeDomain, domain_id, user)
    from sqlalchemy import delete as sa_delete

    await db.execute(
        sa_delete(KnowledgeNote).where(
            KnowledgeNote.folder_id.in_(
                select(KnowledgeFolder.id).where(KnowledgeFolder.domain_id == domain_id)
            )
        )
    )
    await db.execute(sa_delete(KnowledgeFolder).where(KnowledgeFolder.domain_id == domain_id))
    await db.delete(d)
    await db.commit()
    return {"ok": True}


# ---------- folder ----------

@router.post("/domains/{domain_id}/folders")
async def create_folder(
    domain_id: int,
    body: NameIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _owned(db, KnowledgeDomain, domain_id, user)
    f = KnowledgeFolder(user_id=user.id, domain_id=domain_id, name=body.name)
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return {"id": f.id, "name": f.name}


@router.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    f = await _owned(db, KnowledgeFolder, folder_id, user)
    from sqlalchemy import delete as sa_delete

    await db.execute(sa_delete(KnowledgeNote).where(KnowledgeNote.folder_id == folder_id))
    await db.delete(f)
    await db.commit()
    return {"ok": True}


# ---------- note ----------

@router.post("/notes")
async def create_note(
    body: NoteIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _owned(db, KnowledgeFolder, body.folder_id, user)
    n = KnowledgeNote(
        user_id=user.id, folder_id=body.folder_id,
        title=body.title, content_md=body.content_md,
    )
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return {"id": n.id, "title": n.title}


@router.get("/notes/{note_id}")
async def get_note(
    note_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    n = await _owned(db, KnowledgeNote, note_id, user)
    return {
        "id": n.id, "folder_id": n.folder_id, "title": n.title,
        "content_md": n.content_md,
        "created_at": n.created_at.isoformat(), "updated_at": n.updated_at.isoformat(),
    }


@router.put("/notes/{note_id}")
async def update_note(
    note_id: int,
    body: NoteUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    n = await _owned(db, KnowledgeNote, note_id, user)
    data = body.model_dump(exclude_unset=True)
    if "folder_id" in data:
        await _owned(db, KnowledgeFolder, data["folder_id"], user)
    for k, v in data.items():
        setattr(n, k, v)
    await db.commit()
    return {"ok": True}


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    n = await _owned(db, KnowledgeNote, note_id, user)
    await db.delete(n)
    await db.commit()
    return {"ok": True}


# ---------- images ----------

KNOWLEDGE_DIR = Path(settings.files_dir) / "knowledge"


@router.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Upload an image for markdown embedding; returns its URL."""
    if not (file.filename or "").lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持图片文件")
    user_dir = KNOWLEDGE_DIR / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    name = f"{_uuid.uuid4().hex}_{file.filename}"
    (user_dir / name).write_bytes(await file.read())
    return {"ok": True, "url": f"/api/knowledge/images/{user.id}/{name}"}


@router.get("/images/{user_id}/{name}")
async def get_image(user_id: int, name: str, user: User = Depends(get_current_user_or_cookie)):
    """Serve a knowledge image (owner-only). 支持 Cookie 鉴权:Markdown 预览中
    的 <img> 无法携带 Authorization 头,靠登录时写入的 lifeos_token Cookie 访问。"""
    if user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问他人图片")
    path = KNOWLEDGE_DIR / str(user_id) / name
    if not path.exists() or ".." in name or "/" in name or "\\" in name:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片不存在")
    return FileResponse(path)

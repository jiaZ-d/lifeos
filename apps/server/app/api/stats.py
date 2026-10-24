"""Stats (heatmap/trend/weekly/procrastination) + backup export/import (M5)."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections import defaultdict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import DATA_DIR, settings
from ..db import engine, get_db
from ..models import Action, ActionStatus, Entry, EntryCategory, User
from ..services import llm

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/category/{category}")
async def category_stats(
    category: str,
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-category mini stats (P0-2): e.g. 锻炼周时长、饮食健康度、作息睡眠。"""
    from ..models import EntryCategory

    try:
        cat = EntryCategory(category)
    except ValueError:
        raise HTTPException(400, "unknown category")
    entries = (
        await db.execute(
            select(Entry).where(
                Entry.user_id == user.id,
                Entry.primary_category == cat,
                Entry.is_private == False,  # noqa: E712
            )
        )
    ).scalars().all()

    def num(extra, *keys):
        if not extra:
            return None
        for k in keys:
            v = extra.get(k)
            if isinstance(v, (int, float)):
                return float(v)
        return None

    total = len(entries)
    minutes = sum(num(e.extra_json, "minutes", "duration", "时长") or 0 for e in entries)
    sleep = [num(e.extra_json, "sleep_hours", "睡眠时长", "sleep") for e in entries]
    sleep = [s for s in sleep if s is not None]
    diet = [num(e.extra_json, "health", "健康度") for e in entries]
    diet = [d for d in diet if d is not None]
    return {
        "category": category,
        "days": days,
        "total": total,
        "minutes": round(minutes),
        "avg_sleep": round(sum(sleep) / len(sleep), 1) if sleep else None,
        "avg_diet_health": round(sum(diet) / len(diet), 1) if diet else None,
        "recent": [
            {"title": e.title or (e.content or "")[:30], "date": e.created_at.date().isoformat()}
            for e in sorted(entries, key=lambda x: x.created_at, reverse=True)[:10]
        ],
    }


@router.get("/heatmap")
async def heatmap(
    year: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GitHub-style heatmap: date -> (actions done, entries count). Local dates."""
    y = year or dt.date.today().year
    actions = (
        await db.execute(select(Action).where(Action.user_id == user.id))
    ).scalars().all()
    entries = (
        await db.execute(select(Entry).where(Entry.user_id == user.id, Entry.is_private == False))  # noqa: E712
    ).scalars().all()
    acts_by_date: dict[str, int] = defaultdict(int)
    entries_by_date: dict[str, int] = defaultdict(int)
    for a in actions:
        if a.status == ActionStatus.done and a.done_at and a.done_at.year == y:
            acts_by_date[a.done_at.date().isoformat()] += 1
    for e in entries:
        if e.created_at.year == y:
            entries_by_date[e.created_at.date().isoformat()] += 1
    return {
        "year": y,
        "actions": acts_by_date,
        "entries": entries_by_date,
    }


@router.get("/trend")
async def trend(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-day action completion (需求 #2): for each of the last N days,
    how many actions were scheduled and how many were completed."""
    actions = (
        await db.execute(select(Action).where(Action.user_id == user.id))
    ).scalars().all()
    today = dt.date.today()
    cutoff = today - dt.timedelta(days=days - 1)
    by_date: dict[str, dict] = {}
    for i in range(days):
        d = (cutoff + dt.timedelta(days=i)).isoformat()
        by_date[d] = {"planned": 0, "done": 0}
    for a in actions:
        d = a.date.isoformat()
        if d in by_date:
            by_date[d]["planned"] += 1
            if a.status == ActionStatus.done:
                by_date[d]["done"] += 1
    series = [
        {
            "date": d,
            "planned": v["planned"],
            "done": v["done"],
            "rate": round(v["done"] / v["planned"], 2) if v["planned"] else None,
        }
        for d, v in sorted(by_date.items())
    ]
    total_done = sum(v["done"] for v in by_date.values())
    total_planned = sum(v["planned"] for v in by_date.values())
    return {
        "series": series,
        "summary": {
            "done": total_done,
            "planned": total_planned,
            "rate": round(total_done / total_planned, 2) if total_planned else None,
        },
    }


@router.get("/procrastination")
async def procrastination(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Debt / given-up / average postponement (P0-6 supporting stat)."""
    actions = (
        await db.execute(select(Action).where(Action.user_id == user.id))
    ).scalars().all()
    return {
        "debt": sum(1 for a in actions if a.status == ActionStatus.debt),
        "given_up": sum(1 for a in actions if a.status == ActionStatus.given_up),
        "avg_postpone_count": (
            round(sum(a.postpone_count for a in actions) / len(actions), 2) if actions else 0
        ),
    }


@router.get("/weekly-report")
async def weekly_report(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """AI weekly summary with template fallback."""
    now = dt.datetime.now(dt.timezone.utc)
    week_ago = now - dt.timedelta(days=7)
    actions = (
        await db.execute(
            select(Action).where(Action.user_id == user.id, Action.done_at >= week_ago)
        )
    ).scalars().all()
    done = [a for a in actions if a.status == ActionStatus.done]
    debts = [a for a in actions if a.status == ActionStatus.debt]
    facts = (
        f"本周完成行动 {len(done)} 个,合计 {sum(a.minutes for a in done)} 分钟;"
        f"欠账 {len(debts)} 项:{', '.join(a.title for a in debts[:5]) or '无'}。"
    )
    try:
        data = await llm.generate_json(
            "weekly",
            "你是效率教练。基于事实写 150 字以内周报,含完成情况、拖延点、下周建议。只输出 JSON:{\"report\":str}",
            facts,
            {"w": facts[:100]},
            db,
        )
        report = data.get("report", facts)
    except llm.LLMUnavailable:
        report = f"(AI 不可用,离线模板){facts}建议:为欠账行动安排明确时间段。"
    return {"facts": facts, "report": report}


# ---------- backup (BUG-02 修复: 单用户导出,不含其他用户数据) ----------

BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/export")
async def export_backup(user: User = Depends(get_current_user)):
    """只导出当前用户的数据:完整表结构 + 该用户全部业务行(含用户行),
    不再全库 VACUUM(此前会把其他用户数据一并带走)。响应只返回文件名。"""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"lifeos-export-user{user.id}-{stamp}.db"

    live = sqlite3.connect(settings.database_url.replace("sqlite+aiosqlite:///", ""))
    tgt = sqlite3.connect(str(target))
    try:
        # 1) schema: copy table DDL, skipping FTS virtual/shadow tables
        skip_prefix = ("entries_fts",)
        for (name, ddl) in live.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
        ):
            if name.startswith(skip_prefix):
                continue
            tgt.execute(ddl)
        tgt.commit()

        # 2) copy only the current user's rows
        user_tables = [
            "entries", "goals", "tasks", "actions", "projections", "reports",
            "daily_summaries", "privacy_settings", "auto_plan_logs", "user_keys",
        ]
        for table in user_tables:
            cols = [r[1] for r in live.execute(f"PRAGMA table_info({table})")]
            if "user_id" not in cols:
                continue
            rows = live.execute(
                f"SELECT * FROM {table} WHERE user_id = ?", (user.id,)
            ).fetchall()
            if rows:
                ph = ",".join("?" * len(rows[0]))
                tgt.executemany(f"INSERT OR REPLACE INTO {table} VALUES ({ph})", rows)
        # own user row (standalone restore)
        urow = live.execute(
            "SELECT id, username, password_hash, is_admin, created_at FROM users WHERE id = ?",
            (user.id,),
        ).fetchone()
        if urow:
            tgt.execute(
                "INSERT OR REPLACE INTO users (id, username, password_hash, is_admin, created_at)"
                " VALUES (?,?,?,?,?)",
                urow,
            )
        tgt.commit()
    finally:
        live.close()
        tgt.close()
    return {"ok": True, "file": target.name}


@router.post("/import")
async def import_backup(
    conflict: str = "skip",  # skip | overwrite | duplicate
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Import a previously exported backup. Conflict strategy per design P2:
    skip / overwrite / duplicate(by new id). v1 scope: entries table."""
    if conflict not in ("skip", "overwrite", "duplicate"):
        raise HTTPException(400, "conflict must be skip|overwrite|duplicate")
    target = BACKUP_DIR / f"import-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    target.write_bytes(await file.read())
    src = sqlite3.connect(str(target))
    try:
        rows = src.execute(
            "SELECT id, categories, primary_category, title, content, mood, tags, attachments,"
            " is_private, encrypted_blob, extra_json, ai_allowed, created_at, updated_at"
            " FROM entries WHERE user_id = (SELECT MIN(id) FROM entries)"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise HTTPException(400, f"Invalid backup file: {exc}")
    finally:
        src.close()

    from sqlalchemy import delete as sa_delete  # noqa: F811 (re-export for clarity)

    imported = skipped = 0
    async with engine.begin() as conn:
        for r in rows:
            (rid, cats, prim, title, content, mood, tags, atts, priv, blob, extra, ai, created, updated) = r
            if conflict == "overwrite":
                await conn.execute(
                    sa_delete(Entry).where(
                        Entry.user_id == user.id, Entry.created_at == created
                    )
                )
            elif conflict == "skip":
                exists = await conn.execute(
                    select(Entry.id).where(
                        Entry.user_id == user.id,
                        Entry.created_at == created,
                        Entry.title == title,
                    )
                )
                if exists.scalar_one_or_none():
                    skipped += 1
                    continue
            await conn.execute(
                Entry.__table__.insert().values(
                    user_id=user.id,
                    categories=json.loads(cats) if isinstance(cats, str) else cats,
                    primary_category=EntryCategory(prim),
                    title=title,
                    content=content,
                    mood=mood,
                    tags=json.loads(tags) if isinstance(tags, str) else tags,
                    attachments=json.loads(atts) if isinstance(atts, str) else atts,
                    is_private=priv,
                    encrypted_blob=blob,
                    extra_json=json.loads(extra) if isinstance(extra, str) else extra,
                    ai_allowed=ai,
                    created_at=created,
                    updated_at=updated,
                )
            )
            imported += 1
    return {"ok": True, "imported": imported, "skipped": skipped, "conflict": conflict}

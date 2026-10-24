"""Timeline: daily/weekly/monthly/yearly views of entries + editable AI reports."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..db import get_db
from ..models import Action, ActionStatus, Entry, Report, User
from ..services import llm, scope

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


def _period_key(day: dt.date, view: str) -> str:
    if view == "day":
        return day.isoformat()
    if view == "week":
        iso = day.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if view == "month":
        return f"{day.year}-{day.month:02d}"
    return f"{day.year}"


def _period_range(day: dt.date, view: str) -> tuple[dt.date, dt.date]:
    if view == "day":
        return day, day + dt.timedelta(days=1)
    if view == "week":
        start = day - dt.timedelta(days=day.weekday())
        return start, start + dt.timedelta(days=7)
    if view == "month":
        start = day.replace(day=1)
        nxt = (start + dt.timedelta(days=32)).replace(day=1)
        return start, nxt
    return dt.date(day.year, 1, 1), dt.date(day.year + 1, 1, 1)


def _neighbors(day: dt.date, view: str) -> tuple[dt.date, dt.date]:
    """Previous / next period anchor date for navigation."""
    step = {"day": 1, "week": 7, "month": 28, "year": 365}[view]
    if view == "month":
        prev = (day.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
        nxt = (day.replace(day=28) + dt.timedelta(days=8)).replace(day=1)
        return prev, nxt
    if view == "year":
        return dt.date(day.year - 1, 1, 1), dt.date(day.year + 1, 1, 1)
    return day - dt.timedelta(days=step), day + dt.timedelta(days=step)


@router.get("")
async def timeline(
    view: str = Query(default="day", pattern="^(day|week|month|year)$"),
    date: dt.date | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Entries grouped into periods; click a period to see what was done.
    Current period is centered in the strip:
    day -> ±7 days around today; week -> 8 weeks (current in middle);
    month -> 12 months; year -> 5 years (current in middle)."""
    day = date or dt.date.today()
    start, end = _period_range(day, view)

    if view == "day":
        anchors = [day - dt.timedelta(days=i) for i in range(7, 0, -1)] + \
                  [day + dt.timedelta(days=i) for i in range(0, 7)]
    elif view == "week":
        monday = day - dt.timedelta(days=day.weekday())
        anchors = [monday - dt.timedelta(weeks=i) for i in range(4, 0, -1)] + \
                  [monday + dt.timedelta(weeks=i) for i in range(0, 4)]
    elif view == "month":
        first = day.replace(day=1)
        anchors = [(first - dt.timedelta(days=30 * i)).replace(day=1) for i in range(6, 0, -1)] + \
                  [(first + dt.timedelta(days=32 * i)).replace(day=1) for i in range(0, 6)]
    else:
        anchors = [dt.date(day.year - i, 1, 1) for i in range(2, 0, -1)] + \
                  [dt.date(day.year + i, 1, 1) for i in range(0, 3)]

    # counts across the whole strip (not just current period)
    strip_first, strip_last = anchors[0], anchors[-1]
    s_start, _ = _period_range(strip_first, view)
    _, s_end = _period_range(strip_last, view)
    entries = (
        await db.execute(
            select(Entry).where(
                Entry.user_id == user.id,
                Entry.created_at >= dt.datetime.combine(s_start, dt.time.min).astimezone(),
                Entry.created_at < dt.datetime.combine(s_end, dt.time.min).astimezone(),
            )
        )
    ).scalars().all()

    by_period: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        by_period[_period_key(e.created_at.date(), view)].append(e)

    periods = [
        {
            "key": _period_key(a, view),
            "label": {
                "day": a.strftime("%m-%d %a"),
                "week": f"{_period_key(a, 'week')} 周",
                "month": a.strftime("%Y-%m"),
                "year": f"{a.year} 年",
            }[view],
            "count": len(by_period.get(_period_key(a, view), [])),
            "current": _period_key(a, view) == _period_key(day, view),
        }
        for a in anchors
    ]

    def entry_dto(e: Entry) -> dict:
        return {
            "id": e.id,
            "categories": e.categories or [],
            "primary_category": e.primary_category.value if e.primary_category else "",
            "title": "(私密记录)" if e.is_private else (e.title or (e.content or "")[:40]),
            "mood": None if e.is_private else e.mood,
            "is_private": e.is_private,
            "created_at": e.created_at.isoformat(),
        }

    # day view also links that day's todos + the persisted daily summary
    todos = []
    summary_info = None
    if view == "day":
        from ..models import DailySummary

        actions = (
            await db.execute(
                select(Action).where(Action.user_id == user.id, Action.date == day)
            )
        ).scalars().all()
        todos = [
            {
                "id": a.id,
                "title": a.title,
                "minutes": a.minutes,
                "status": a.status.value,
                "task_id": a.task_id,
            }
            for a in sorted(actions, key=lambda x: (x.status != ActionStatus.done, x.id))
        ]
        stored = (
            await db.execute(
                select(DailySummary).where(
                    DailySummary.user_id == user.id, DailySummary.summary_date == day
                )
            )
        ).scalar_one_or_none()
        if stored is not None:
            summary_info = {"content_md": stored.content_md, "ai_generated": stored.ai_generated}

    prev_a, next_a = _neighbors(day, view)
    return {
        "view": view,
        "anchor": day.isoformat(),
        "period_key": _period_key(day, view),
        "range": [start.isoformat(), end.isoformat()],
        "prev": prev_a.isoformat(),
        "next": next_a.isoformat(),
        "periods": periods,
        "entries": [entry_dto(e) for e in sorted(by_period.get(_period_key(day, view), []), key=lambda x: x.created_at)],
        "todos": todos,
        "summary": summary_info,
    }


# ---------- periodic reports (AI generated, user editable) ----------

class ReportGenIn(BaseModel):
    period_type: str  # week | month | year
    period_key: str   # e.g. 2026-W42 / 2026-10 / 2026
    force_refresh: bool = False


class ReportUpdateIn(BaseModel):
    content_md: str


@router.get("/reports/{period_type}/{period_key}")
async def get_report(
    period_type: str,
    period_key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = (
        await db.execute(
            select(Report).where(
                Report.user_id == user.id,
                Report.period_type == period_type,
                Report.period_key == period_key,
            )
        )
    ).scalar_one_or_none()
    if r is None:
        return {"exists": False, "content_md": "", "ai_generated": True}
    return {"exists": True, "content_md": r.content_md, "ai_generated": r.ai_generated, "updated_at": r.updated_at.isoformat()}


@router.put("/reports/{period_type}/{period_key}")
async def update_report(
    period_type: str,
    period_key: str,
    body: ReportUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User edits the report in the UI; edits are persisted (ai_generated -> False)."""
    if period_type not in ("week", "month", "year"):
        raise HTTPException(400, "period_type must be week|month|year")
    r = (
        await db.execute(
            select(Report).where(
                Report.user_id == user.id,
                Report.period_type == period_type,
                Report.period_key == period_key,
            )
        )
    ).scalar_one_or_none()
    if r is None:
        r = Report(user_id=user.id, period_type=period_type, period_key=period_key, content_md=body.content_md)
        db.add(r)
    else:
        r.content_md = body.content_md
        r.ai_generated = False  # user-modified
    await db.commit()
    return {"ok": True, "ai_generated": r.ai_generated}


async def _collect_facts(db: AsyncSession, user: User, start: dt.date, end: dt.date, view: str) -> dict:
    entries = (
        await db.execute(
            select(Entry).where(
                Entry.user_id == user.id,
                Entry.created_at >= dt.datetime.combine(start, dt.time.min).astimezone(),
                Entry.created_at < dt.datetime.combine(end, dt.time.min).astimezone(),
            )
        )
    ).scalars().all()
    allowed = {e.id for e in await scope.ai_visible_entries(db, user.id)}
    cats: dict[str, int] = defaultdict(int)
    lines: list[str] = []
    for e in entries:
        if e.is_private or e.id not in allowed:
            continue
        cats[e.primary_category.value] += 1
        lines.append(f"[{e.primary_category.value}] {(e.title or e.content or '')[:60]}")
    return {
        "period": f"{view} {_period_key(start, view)}",
        "category_counts": dict(cats),
        "total_entries": len(entries),
        "sample": "\n".join(lines[:40]),
    }


@router.post("/reports/generate")
async def generate_report(
    body: ReportGenIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI generates the report for a period; user can then edit via PUT."""
    if body.period_type not in ("week", "month", "year"):
        raise HTTPException(400, "period_type must be week|month|year")
    key = body.period_key
    try:
        if body.period_type == "week":
            year, week = int(key[:4]), int(key.split("W")[1])
            day = dt.date.fromisocalendar(year, week, 1)
        elif body.period_type == "month":
            day = dt.date(int(key[:4]), int(key[5:7]), 1)
        else:
            day = dt.date(int(key), 6, 1)
    except Exception:
        raise HTTPException(400, "invalid period_key format")

    start, end = _period_range(day, body.period_type)
    facts = await _collect_facts(db, user, start, end, body.period_type)

    label = {"week": "周报", "month": "月报", "year": "年报"}[body.period_type]
    system = (
        f"你是个人助理。基于用户的记录事实,写一份{label},Markdown 格式,包含:概述、"
        "按分类的要点、亮点与不足、下期建议。只输出 JSON:{\"report\":str}。"
    )
    user_msg = f"周期:{facts['period']}\n分类统计:{facts['category_counts']}\n记录数:{facts['total_entries']}\n记录摘录:\n{facts['sample'] or '(该周期无记录)'}"
    try:
        data = await llm.generate_json(f"report_{body.period_type}", system, user_msg, {"k": key}, db)
        content = data.get("report", "(生成失败,请重试)")
        degraded = False
    except llm.LLMUnavailable:
        content = (
            f"# {label} · {facts['period']}\n\n(AI 服务不可用,以下为记录摘录模板)\n\n"
            f"- 分类统计:{facts['category_counts']}\n- 记录数:{facts['total_entries']}\n\n"
            + "\n".join(f"- {l}" for l in facts["sample"].splitlines()[:10])
        )
        degraded = True

    # generate always overwrites stored version (user edited marker resets)
    r = (
        await db.execute(
            select(Report).where(
                Report.user_id == user.id,
                Report.period_type == body.period_type,
                Report.period_key == key,
            )
        )
    ).scalar_one_or_none()
    if r is None:
        r = Report(user_id=user.id, period_type=body.period_type, period_key=key, content_md=content)
        db.add(r)
    else:
        r.content_md = content
        r.ai_generated = True
    await db.commit()
    return {"ok": True, "content_md": r.content_md, "degraded": degraded, "facts": facts}

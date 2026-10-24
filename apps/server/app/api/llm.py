"""LLM endpoints: task generation, action splitting, daily summary (M3)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_admin_user, get_current_user
from ..db import get_db
from ..models import Action, Entry, Goal, Granularity, Task, User
from ..services import llm, scope

router = APIRouter(prefix="/api/llm", tags=["llm"])


class GenTasksIn(BaseModel):
    goal_id: int
    granularity: Granularity
    profile_summary: str | None = None
    force_refresh: bool = False


class GenActionsIn(BaseModel):
    task_id: int
    preference: str | None = None


async def _profile_summary(db: AsyncSession, user: User) -> str:
    """Context built only from AI-authorized entries (scope.py intersection)."""
    entries = await scope.ai_visible_entries(db, user.id)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)
    lines = [
        f"[{e.primary_category.value}] {(e.title or e.content or '')[:80]}"
        for e in entries
        if e.created_at.replace(tzinfo=dt.timezone.utc) >= cutoff
    ]
    return "\n".join(lines[-50:])


@router.post("/generate-tasks")
async def generate_tasks(
    body: GenTasksIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    goal = (
        await db.execute(select(Goal).where(Goal.id == body.goal_id, Goal.user_id == user.id))
    ).scalar_one_or_none()
    if goal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found")
    profile = body.profile_summary or await _profile_summary(db, user)
    try:
        tasks = await llm.generate_tasks(db, goal.title, goal.description or "", body.granularity.value, profile)
        cached = any(t.get("_cached") for t in tasks if isinstance(t, dict))
    except llm.LLMUnavailable as exc:
        tasks = llm.fallback_tasks(goal.title, body.granularity.value)
        cached = False
        degraded = True
        return {"tasks": tasks, "degraded": True, "cached": False, "error": str(exc)}
    else:
        degraded = False
    return {"tasks": tasks, "degraded": degraded, "cached": cached}


@router.post("/generate-actions")
async def generate_actions(
    body: GenActionsIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    task = (
        await db.execute(select(Task).where(Task.id == body.task_id, Task.user_id == user.id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    try:
        actions = await llm.generate_actions(db, task.title, body.preference or "")
        degraded = False
    except llm.LLMUnavailable:
        actions = [
            {"title": f"第一步:{task.title[:20]} 准备", "minutes": 20},
            {"title": f"执行:{task.title[:20]}", "minutes": 45},
            {"title": f"回顾:{task.title[:20]} 结果", "minutes": 15},
        ]
        degraded = True
    return {"actions": actions, "degraded": degraded}


class SummaryIn(BaseModel):
    date: dt.date | None = None
    force_refresh: bool = False


async def build_daily_summary_text(db: AsyncSession, user: User, day: dt.date) -> tuple[str, dict]:
    entries = (
        await db.execute(
            select(Entry).where(
                Entry.user_id == user.id,
                Entry.created_at >= dt.datetime.combine(day, dt.time.min).astimezone(),
                Entry.created_at < dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min).astimezone(),
            )
        )
    ).scalars().all()
    # privacy: encrypted entries excluded; AI scope filter applies
    allowed_ids = {e.id for e in await scope.ai_visible_entries(db, user.id)}
    lines = [
        f"[{e.primary_category.value}] {(e.title or e.content or '')[:100]}"
        for e in entries
        if e.id in allowed_ids and not e.is_private
    ]
    # 关联今日待办完成情况(需求:小结须包含已完成的待办)
    actions = (
        await db.execute(
            select(Action).where(Action.user_id == user.id, Action.date == day)
        )
    ).scalars().all()
    done_actions = [a for a in actions if a.status.value == "done"]
    debt_actions = [a for a in actions if a.status.value == "debt"]
    action_lines = [f"✓ {a.title}" for a in done_actions]
    action_lines += [f"○ {a.title}(未完成)" for a in actions if a.status.value == "open"]
    todo_text = (
        f"今日待办({len(done_actions)}/{len(actions)} 已完成):\n"
        + ("\n".join(action_lines) if action_lines else "(今天没有安排待办)")
    )
    if debt_actions:
        todo_text += f"\n欠账 {len(debt_actions)} 项:" + "、".join(a.title for a in debt_actions[:5])
    text = f"{day.isoformat()} 的记录:\n" + ("\n".join(lines) if lines else "(今天还没有可总结的记录)") + f"\n\n{todo_text}"
    meta = {"todos": {"total": len(actions), "done": len(done_actions), "debt": len(debt_actions)}, "entry_count": len(lines)}
    return text, meta


async def ensure_daily_summary(db: AsyncSession, user: User, day: dt.date, force: bool = False) -> dict:
    """Return stored summary for the day; generate if missing (or force).
    Used by the API and the 01:00 scheduler (previous-day job)."""
    from ..models import DailySummary

    stored = (
        await db.execute(
            select(DailySummary).where(
                DailySummary.user_id == user.id, DailySummary.summary_date == day
            )
        )
    ).scalar_one_or_none()
    if stored is not None and not force:
        return {"date": day.isoformat(), "summary": stored.content_md,
                "ai_generated": stored.ai_generated, "regenerated": False}
    text, meta = await build_daily_summary_text(db, user, day)
    summary = await llm.generate_daily_summary(db, text)
    if stored is None:
        stored = DailySummary(user_id=user.id, summary_date=day, content_md=summary)
        db.add(stored)
    else:
        stored.content_md = summary
        stored.ai_generated = True
    await db.commit()
    return {"date": day.isoformat(), "summary": summary, "ai_generated": True,
            "regenerated": True, **meta}


@router.post("/daily-summary")
async def daily_summary(
    body: SummaryIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    day = body.date or dt.date.today()
    result = await ensure_daily_summary(db, user, day, force=body.force_refresh)
    if "todos" not in result:  # stored hit: recompute meta for UI
        _, meta = await build_daily_summary_text(db, user, day)
        result.update(meta)
    return result


class SummaryEditIn(BaseModel):
    content_md: str


@router.get("/daily-summary")
async def get_daily_summary(
    date: dt.date | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stored-only lookup (no LLM call): for showing an existing summary by default."""
    from ..models import DailySummary

    day = date or dt.date.today()
    stored = (
        await db.execute(
            select(DailySummary).where(
                DailySummary.user_id == user.id, DailySummary.summary_date == day
            )
        )
    ).scalar_one_or_none()
    if stored is None:
        return {"exists": False, "summary": "", "ai_generated": True}
    return {"exists": True, "summary": stored.content_md, "ai_generated": stored.ai_generated}


@router.put("/daily-summary/{day}")
async def edit_daily_summary(
    day: dt.date, body: SummaryEditIn,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """User edits the summary in the UI; persists with ai_generated=False."""
    from ..models import DailySummary

    stored = (
        await db.execute(
            select(DailySummary).where(
                DailySummary.user_id == user.id, DailySummary.summary_date == day
            )
        )
    ).scalar_one_or_none()
    if stored is None:
        stored = DailySummary(user_id=user.id, summary_date=day, content_md=body.content_md, ai_generated=False)
        db.add(stored)
    else:
        stored.content_md = body.content_md
        stored.ai_generated = False
    await db.commit()
    return {"ok": True, "ai_generated": stored.ai_generated}


@router.get("/models")
async def list_models(user: User = Depends(get_current_user)):
    """Model picker source: try the provider's OpenAI-compatible /models listing;
    fall back to a preset list of known Zhipu models."""
    import httpx

    from ..config import load_llm_config

    cfg = load_llm_config()
    base_url = (cfg.get("base_url") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
    api_key = cfg.get("api_key")
    source = "preset"
    models: list[str] = []
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
            if r.status_code == 200:
                data = r.json()
                items = data.get("data", data if isinstance(data, list) else [])
                models = sorted(
                    m.get("id") for m in items if isinstance(m, dict) and m.get("id")
                )
                if models:
                    source = "provider"
        except Exception:
            pass
    if not models:
        models = PRESET_MODELS
    return {"models": models, "source": source}


PRESET_MODELS = [
    "glm-5.3-flash",
    "glm-5.3",
    "glm-5.2",
    "glm-4.5",
    "glm-4.5-flash",
]


class LLMConfigIn(BaseModel):
    base_url: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=64)
    api_key: str | None = Field(default=None, max_length=256)


@router.get("/config")
async def get_config(user: User = Depends(get_current_user)):
    from ..config import load_llm_config

    cfg = load_llm_config()
    key = cfg.get("api_key") or ""
    masked = f"{'*' * max(6, len(key) - 4)}{key[-4:]}" if key else ""
    return {
        "base_url": cfg.get("base_url") or "https://open.bigmodel.cn/api/paas/v4",
        "model": cfg.get("model") or "glm-5.3-flash",
        "has_api_key": bool(key),
        "api_key_masked": masked,
    }


@router.get("/config/reveal")
async def reveal_key(admin: User = Depends(get_admin_user)):
    """Admin only: return the stored key so the owner can view it."""
    from ..config import load_llm_config

    return {"api_key": load_llm_config().get("api_key") or ""}


@router.put("/config")
async def set_config(body: LLMConfigIn, admin: User = Depends(get_admin_user)):
    """Admin only: persist LLM endpoint/model/key to config/llm_config.json."""
    from ..config import load_llm_config, save_llm_config
    from ..services import llm as llm_svc

    cfg = load_llm_config()
    if body.base_url is not None:
        cfg["base_url"] = body.base_url.strip()
    if body.model is not None:
        cfg["model"] = body.model.strip()
    if body.api_key is not None:
        cfg["api_key"] = body.api_key.strip()
    save_llm_config(cfg)
    llm_svc.set_api_key(cfg.get("api_key"))
    return {"ok": True, "model": cfg.get("model"), "base_url": cfg.get("base_url")}


@router.post("/test")
async def test_llm(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Connectivity test: returns real provider error when failing."""
    try:
        data = await llm.generate_json(
            "test", "你是回声服务。只输出 JSON:{\"ok\":true}", "ping", {"ping": True}, db
        )
        return {"ok": True, "cached": data.get("_cached", False)}
    except llm.LLMUnavailable as exc:
        return {"ok": False, "error": str(exc)}

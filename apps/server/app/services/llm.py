"""LLM adapter: OpenAI-compatible endpoint, default Zhipu GLM (design §5).

Rules (P1-4): JSON parse failure -> retry with error feedback (max 2),
timeout 60s, cache 24h in llm_cache table, template fallback on failure.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import load_llm_config, save_llm_config, settings
from ..models import LLMCache

log = logging.getLogger("lifeos.llm")

PROMPT_VERSION = "v1"


class LLMUnavailable(Exception):
    pass


def _runtime() -> dict:
    """Effective LLM settings: persisted config overrides defaults (model/base_url/api_key)."""
    cfg = load_llm_config()
    return {
        "base_url": cfg.get("base_url") or settings.llm_base_url,
        "model": cfg.get("model") or settings.llm_model,
        "api_key": cfg.get("api_key") or _API_KEY,
    }


def _cache_key(func: str, payload: dict) -> str:
    cfg = _runtime()
    raw = json.dumps({"f": func, "p": payload, "v": PROMPT_VERSION, "m": cfg["model"]}, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


async def _cache_get(_db: AsyncSession, key: str) -> dict | None:
    """Uses its OWN short session so cache errors never poison the request session."""
    from ..db import SessionLocal

    async with SessionLocal() as db:
        row = (
            await db.execute(select(LLMCache).where(LLMCache.cache_key == key))
        ).scalar_one_or_none()
        if row is None:
            return None
        created = row.created_at
        if created.tzinfo is None:  # SQLite returns naive datetimes
            created = created.replace(tzinfo=dt.timezone.utc)
        age = dt.datetime.now(dt.timezone.utc) - created
        if age > dt.timedelta(hours=settings.llm_cache_hours):
            await db.delete(row)  # drop expired row so re-insert won't collide
            await db.commit()
            return None
        return json.loads(row.response)


async def _cache_put(_db: AsyncSession, key: str, response: dict) -> None:
    """Upsert into llm_cache using its OWN short session (never poisons the
    request session; concurrent/duplicate keys are handled by delete-then-insert)."""
    from ..db import SessionLocal

    async with SessionLocal() as db:
        try:
            await db.execute(sa_delete(LLMCache).where(LLMCache.cache_key == key))
            db.add(LLMCache(cache_key=key, response=json.dumps(response, ensure_ascii=False)))
            await db.commit()
        except Exception as exc:
            await db.rollback()
            log.warning("llm cache put failed (ignored): %s", exc)


async def _call_glm(messages: list[dict], force_json: bool) -> str:
    """Async openai-SDK call against the configured OpenAI-compatible endpoint."""
    from openai import AsyncOpenAI

    cfg = _runtime()
    if not cfg["api_key"]:
        raise LLMUnavailable("LLM API key not configured (set it in Settings)")
    client = AsyncOpenAI(
        api_key=cfg["api_key"], base_url=cfg["base_url"], timeout=settings.llm_timeout_seconds
    )
    kwargs: dict = {"model": cfg["model"], "messages": messages}
    if force_json:
        kwargs["response_format"] = {"type": "json_object"}
    resp = await client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


_API_KEY: str | None = None


def set_api_key(key: str | None) -> None:
    global _API_KEY
    _API_KEY = key


async def generate_json(func: str, system: str, user: str, payload: dict, db: AsyncSession) -> dict:
    """Cached, retrying JSON generation. Raises LLMUnavailable on final failure."""
    key = _cache_key(func, payload)
    cached = await _cache_get(db, key)
    if cached is not None:
        return {**cached, "_cached": True}

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_error: Exception | None = None
    for attempt in range(settings.llm_max_retries + 1):
        try:
            text = await _call_glm(messages, force_json=True)
            data = json.loads(text)
            await _cache_put(db, key, data)
            return {**data, "_cached": False}
        except LLMUnavailable:
            raise
        except Exception as exc:  # parse error / network error -> retry with feedback
            last_error = exc
            await db.rollback()  # un-poison the request session before retrying
            log.warning("llm attempt %d failed: %s", attempt + 1, exc)
            messages.append({"role": "assistant", "content": str(exc)[:500]})
            messages.append(
                {
                    "role": "user",
                    "content": f"上一次输出不符合 JSON Schema 要求({exc})。请重新输出,只输出合法 JSON。",
                }
            )
    raise LLMUnavailable(f"LLM failed after retries: {last_error}")


# ---------- prompts ----------

GRANULARITY_CN = {"year": "年度", "month": "月度", "week": "周"}

# Granularity-specific guidance so year/month/week tasks differ in scope (issue #3)
GRANULARITY_GUIDE = {
    "year": "年度任务=阶段性里程碑成果(如'完成认证考试'、'发布产品1.0'),不写日常动作",
    "month": "月度任务=本月要交付的具体成果(如'完成前三章学习并做完练习题'),比年度任务小、比周任务大,不写'每周…'这种周期性表述",
    "week": "周任务=本周可完成的 Specific 行动块(如'刷完两套真题并复盘错题'),以'完成/产出'开头,不与月任务重复",
}


async def generate_tasks(
    db: AsyncSession,
    goal_title: str,
    goal_description: str,
    granularity: str,
    profile_summary: str,
    parent_context: str | None = None,
) -> list[dict]:
    guide = GRANULARITY_GUIDE.get(granularity, "")
    system = (
        "你是目标管理专家。基于用户目标与现状,生成任务草稿。只输出 JSON:"
        '{"tasks":[{"title":str,"priority":1|2|3,"estimate_hours":number,"due_hint":str}]}'
        "。任务数量 2-4 个,标题具体、可验收。\n"
        f"本粒度要求:{guide}。\n"
        "各粒度任务不得互相重复:年度=里程碑,月度=阶段成果,周=具体行动块。"
    )
    parent_line = f"\n上级任务(拆解来源,子任务必须是对它的具体化展开,不得照抄):{parent_context}" if parent_context else ""
    user = f"目标:{goal_title}\n说明:{goal_description or '无'}\n粒度:{GRANULARITY_CN.get(granularity, granularity)}{parent_line}\n现状:{profile_summary or '无记录'}"
    data = await generate_json("gen_tasks", system, user, {"goal": goal_title, "g": granularity, "p": parent_context or ""}, db)
    return data.get("tasks", [])


async def generate_month_plan(
    db: AsyncSession, goal_title: str, parent_title: str, months: int, profile_summary: str
) -> list[dict]:
    """Year task -> monthly PROGRESS PLAN from now to the expected completion,
    循序渐进: early months lay foundations (lower load), later months advance
    and sprint (higher load), cumulative progress tracking the timeline."""
    system = (
        f"你是计划专家。把年度任务拆解为从当前月份到预期完成月份共 {months} 个月的**月度进度规划**。"
        "要求循序渐进:第1个月从打基础、低强度起步;中间月份逐步进阶加大投入;"
        "最后1-2个月冲刺收尾并验收成果。累计进度随时间推进(如 10%→30%→60%→100%)。"
        "只输出 JSON:"
        '{"plan":[{"month_offset":1,"title":"第1月:…(基础起步),累计进度约10%","priority":1|2|3,"estimate_hours":number}]}'
        "。month_offset 从 1 连续递增到 " + str(months) + ";title 以'第N月:'开头;"
        "estimate_hours 也应循序渐进(前少后多);各月成果递进,不得重复。"
    )
    user = f"目标:{goal_title}\n年度任务:{parent_title}\n月数:{months}(当前月=第1月,最后一个月=预期完成月)\n现状:{profile_summary or '无记录'}"
    data = await generate_json(
        "month_plan", system, user, {"goal": goal_title, "m": months}, db
    )
    return data.get("plan", data.get("tasks", []))


async def generate_goal_suggestions(db: AsyncSession, report: dict, horizon_years: int) -> list[dict]:
    """Based on a projection report, suggest goals the user could set (issue #2)."""
    system = (
        "你是人生规划教练。基于未来推演报告,建议用户应当设定的目标(3-5 个),"
        "每个目标给出:标题、一句话说明、维度。只输出 JSON:"
        '{"suggestions":[{"title":str,"description":str,"dimension":"growth|career|health|finance|relationship"}]}'
        f"。目标应针对报告中的关键变量与改善路线,时间跨度与推演期({horizon_years} 年)匹配,部分目标可以是 1 年内可起步的。"
    )
    user_msg = (
        f"改善路线:{report.get('improved', '')}\n"
        f"关键变量:{report.get('key_variables', [])}\n"
        f"外部趋势:{report.get('external_trends', {})}\n"
        f"健康基线:{report.get('radar', {}).get('health', '')}"
    )
    data = await generate_json(
        "goal_suggestions", system, user_msg, {"h": horizon_years, "kv": str(report.get("key_variables", []))[:100]}, db
    )
    return data.get("suggestions", [])


def fallback_goal_suggestions(report: dict, horizon_years: int) -> list[dict]:
    kvs = report.get("key_variables") or ["规律锻炼", "持续学习", "职业深耕"]
    dims = ["health", "growth", "career", "finance", "relationship"]
    out = []
    for i, kv in enumerate(kvs[:3]):
        out.append({
            "title": f"围绕「{kv}」建立长期习惯体系",
            "description": f"针对推演指出的关键变量「{kv}」,在 {horizon_years} 年内形成稳定习惯并逐年提升。",
            "dimension": dims[i % len(dims)],
        })
    return out


async def generate_actions(
    db: AsyncSession, task_title: str, preference: str
) -> list[dict]:
    system = (
        "你是任务拆解专家。把任务拆解为每日行动,每个行动 15-60 分钟、可勾选。只输出 JSON:"
        '{"actions":[{"title":str,"minutes":int}]}'
        "。行动数量 2-6 个。"
    )
    user = f"任务:{task_title}\n日程偏好:{preference or '无'}"
    data = await generate_json("gen_actions", system, user, {"task": task_title}, db)
    return data.get("actions", [])


async def generate_daily_summary(db: AsyncSession, entries_text: str) -> str:
    system = (
        "你是个人助理。基于用户当天的记录和待办完成情况写一段 100-200 字的今日小结,"
        "Markdown 格式:先总结已完成的待办(✓ 项),再概括当天记录要点,语气温和具体。"
    )
    try:
        digest = hashlib.sha256(entries_text.encode()).hexdigest()[:16]
        data = await generate_json("daily_summary", system, entries_text, {"digest": digest}, db)
        return data.get("summary") or str(data)
    except LLMUnavailable:
        return _fallback_summary(entries_text)


def _fallback_summary(entries_text: str) -> str:
    lines = [l for l in entries_text.strip().splitlines() if l.strip()][:14]
    return "### 今日小结(离线模板)\n\n" + "\n".join(f"- {l}" for l in lines) + "\n\n(AI 服务不可用,以上为记录与待办摘录)"


def fallback_tasks(goal_title: str, granularity: str) -> list[dict]:
    """Degraded template tasks when LLM is unavailable (design §5)."""
    label = GRANULARITY_CN.get(granularity, granularity)
    return [
        {"title": f"[{label}]规划「{goal_title}」的第一步", "priority": 1, "estimate_hours": 1, "due_hint": "本周"},
        {"title": f"[{label}]执行「{goal_title}」核心练习 3 次", "priority": 2, "estimate_hours": 3, "due_hint": "本周内"},
        {"title": f"[{label}]回顾「{goal_title}」进展并调整", "priority": 3, "estimate_hours": 0.5, "due_hint": "周末"},
    ]

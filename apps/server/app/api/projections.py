"""Ten-year projection: 4-source input, cold start, archiving (M4)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..db import get_db
from ..models import Goal, GoalStatus, Projection, Task, User
from ..services import health, llm, scope

router = APIRouter(prefix="/api/projections", tags=["projections"])

DISCLAIMER = "AI 生成内容,仅供参考,不构成任何投资、职业或医疗建议。"


class ProjectionIn(BaseModel):
    horizon_years: int = Field(default=10, ge=1, le=30)  # 可选择推演年数(需求 #1)
    questionnaire: dict[str, int] = Field(default_factory=dict)
    society_trend: str | None = None
    industry: str | None = None
    role: str | None = None
    industry_years: int | None = None
    use_personal_data: bool = True


async def _personal_snapshot(db: AsyncSession, user: User) -> dict:
    goals = (await db.execute(select(Goal).where(Goal.user_id == user.id))).scalars().all()
    tasks = (await db.execute(select(Task).where(Task.user_id == user.id))).scalars().all()
    done_tasks = sum(1 for t in tasks if t.status.value == "done")
    entries = await scope.ai_visible_entries(db, user.id)
    return {
        "goal_count": len(goals),
        "goals": [g.title for g in goals[:10]],
        "task_completion_rate": round(done_tasks / len(tasks), 2) if tasks else None,
        "recent_entry_count": len(entries),
    }


@router.post("")
async def create_projection(
    body: ProjectionIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    personal = await _personal_snapshot(db, user) if body.use_personal_data else {}
    health_base = await health.estimate_health(db, user.id)
    cold_start = body.use_personal_data and personal.get("recent_entry_count", 0) < 14  # P1-5

    # 显式参考项:用户已设定的目标(需求 #1)
    user_goals = (
        await db.execute(
            select(Goal).where(Goal.user_id == user.id, Goal.status == GoalStatus.active)
        )
    ).scalars().all()

    h = body.horizon_years
    system = (
        f"你是人生规划推演专家。综合个人现状(含用户已设定的目标)、社会趋势、行业趋势、健康基线,"
        f"输出未来 {h} 年的推演。只输出 JSON:"
        '{"maintained":str,"improved":str,"radar":{"health":[num,num],"finance":[num,num],'
        '"career":[num,num],"relationship":[num,num],"growth":[num,num]},'
        f'"milestones":[{{"year":str,"personal":str,"industry":str}},...],'
        '"key_variables":[str,str,str],"external_trends":{"society":str,"industry":str},"confidence":"high|medium|low"}'
        f"。radar 数值为 [现状, {h} 年后预测],1-10。milestones 覆盖 {h} 年内合理节点"
        f"(如 {h}>=3 时给 1/{max(2, h//3)}/{h} 年等,不要固定 10 年)。"
    )
    user_msg = (
        f"推演年数:{h} 年\n"
        f"个人现状:{personal}\n"
        f"用户已设定的目标(推演时必须参考,评估其现状与可达性):{[g.title for g in user_goals] or '尚未设定'}\n"
        f"现状问卷:{body.questionnaire}\n"
        f"健康基线:{health_base}\n"
        f"社会趋势:{body.society_trend or '由你基于知识判断'}\n"
        f"行业:{body.industry or '未提供'},岗位:{body.role or '未提供'},年限:{body.industry_years or '未知'}\n"
        + ("注意:个人数据不足 14 天,请主要依赖问卷与外部参数,confidence=low。" if cold_start else "")
    )
    payload = {"industry": body.industry, "cold": cold_start, "h": h}
    try:
        report = await llm.generate_json("projection", system, user_msg, payload, db)
        degraded = False
    except llm.LLMUnavailable:
        report = {
            "maintained": "(AI 服务不可用)基于健康基线:维持现状下," + health_base["outlook_10y"],
            "improved": "(AI 服务不可用)建议先补全记录并配置 LLM API Key 后重新生成。",
            "radar": {},
            "milestones": [],
            "key_variables": ["锻炼频率", "睡眠时长", "目标执行率"],
            "external_trends": {"society": body.society_trend or "(待生成)", "industry": body.industry or "(待生成)"},
            "confidence": "low",
        }
        degraded = True

    if cold_start and report.get("confidence") not in (None, "low"):
        report["confidence"] = "low"

    p = Projection(
        user_id=user.id,
        input_snapshot_json={
            "horizon_years": h,
            "questionnaire": body.questionnaire,
            "society_trend": body.society_trend,
            "industry": body.industry,
            "role": body.role,
            "industry_years": body.industry_years,
            "use_personal_data": body.use_personal_data,
            "cold_start": cold_start,
            "health_baseline": health_base,
            "referenced_goals": [g.title for g in user_goals],
        },
        snapshot_json=report,
        report_md=DISCLAIMER,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return {
        "id": p.id,
        "created_at": p.created_at.isoformat(),
        "horizon_years": h,
        "report": report,
        "health_baseline": health_base,
        "cold_start": cold_start,
        "degraded": degraded,
        "disclaimer": DISCLAIMER,
    }


@router.get("")
async def list_projections(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Projection).where(Projection.user_id == user.id).order_by(Projection.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "horizon_years": r.input_snapshot_json.get("horizon_years", 10),
            "confidence": r.snapshot_json.get("confidence"),
            "input": r.input_snapshot_json,
            "report": r.snapshot_json,
            "suggestions": r.suggestions_json or [],
            "disclaimer": DISCLAIMER,
        }
        for r in rows
    ]


# ---------- 需求 #2:推演后建议目标,确认后生成目标计划 ----------

class SuggestionIn(BaseModel):
    horizon_years: int = Field(default=10, ge=1, le=30)


@router.post("/{projection_id}/suggest-goals")
async def suggest_goals(
    projection_id: int,
    body: SuggestionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = (
        await db.execute(select(Projection).where(Projection.id == projection_id, Projection.user_id == user.id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projection not found")
    h = body.horizon_years or p.input_snapshot_json.get("horizon_years", 10)
    try:
        suggestions = await llm.generate_goal_suggestions(db, p.snapshot_json, h)
        degraded = False
    except llm.LLMUnavailable:
        suggestions = llm.fallback_goal_suggestions(p.snapshot_json, h)
        degraded = True
    p.suggestions_json = suggestions  # persist so refresh keeps them
    await db.commit()
    return {"suggestions": suggestions, "degraded": degraded}


class ApplySuggestionIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = None
    dimension: str | None = None
    with_tasks: bool = True  # 确认后自动生成年度→月度→周的任务计划


@router.post("/apply-suggestion")
async def apply_suggestion(
    body: ApplySuggestionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User confirms a suggestion -> create the goal, and if with_tasks,
    progressively build year -> month -> week tasks (LLM or template)."""
    from ..models import GoalStatus, Task as TaskModel, Granularity as Gran
    from ..services import llm as llm_svc

    goal = Goal(user_id=user.id, title=body.title, description=body.description,
                dimension=body.dimension, status=GoalStatus.active)
    db.add(goal)
    await db.flush()
    await db.commit()  # commit the goal FIRST; don't hold a write txn across LLM awaits

    task_tree = {"created": 0, "degraded": False}
    if body.with_tasks:
        profile = "\n".join(
            f"[{e.primary_category.value}] {(e.title or e.content or '')[:60]}"
            for e in await scope.ai_visible_entries(db, user.id)
        )[:600]

        async def _mk(parent: TaskModel | None, gran: Gran) -> TaskModel | None:
            try:
                children = await llm_svc.generate_tasks(
                    db, body.title, body.description or "", gran.value, profile,
                    parent_context=parent.title if parent else None,
                )
                task_tree["degraded"] = task_tree["degraded"] or False
            except llm_svc.LLMUnavailable:
                if parent is not None:
                    return None  # no key: only build the first level from templates
                children = llm_svc.fallback_tasks(body.title, gran.value)
                task_tree["degraded"] = True
            first = None
            for c in children[:3]:  # cap per level to keep the plan lean
                ct = TaskModel(
                    user_id=user.id, goal_id=goal.id,
                    parent_task_id=parent.id if parent else None,
                    granularity=gran, title=c.get("title", ""),
                    priority=c.get("priority", 2), estimate_hours=c.get("estimate_hours"),
                )
                db.add(ct)
                await db.flush()
                task_tree["created"] += 1
                if first is None:
                    first = ct
            return first

        # 逐级拆分:年度 -> 每个年度任务的第一个建月度 -> 月度的第一个建周(保持计划精简)
        years = await _mk(None, Gran.year)
        await db.commit()
        node = years
        for gran in (Gran.month, Gran.week):
            if node is None:
                break
            node = await _mk(node, gran)
            await db.commit()

    return {
        "ok": True,
        "goal": {"id": goal.id, "title": goal.title, "dimension": goal.dimension},
        "tasks_created": task_tree["created"],
        "degraded": task_tree["degraded"],
    }

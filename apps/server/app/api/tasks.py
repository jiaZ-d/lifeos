"""Goals / multi-granularity tasks / actions / board / today+debt (M2)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth import get_current_user
from ..db import get_db
from ..models import (
    Action,
    ActionStatus,
    Goal,
    GoalStatus,
    Granularity,
    Task,
    TaskStatus,
    User,
    utcnow,
)

router = APIRouter(prefix="/api", tags=["goals-tasks-actions"])

POSTPONE_LIMIT = 3  # design P0-6


# ---------- schemas ----------

class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = None
    category: str | None = None
    dimension: str | None = None
    deadline: dt.date | None = None


class GoalUpdateIn(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    dimension: str | None = None
    deadline: dt.date | None = None
    status: GoalStatus | None = None


class TaskIn(BaseModel):
    goal_id: int | None = None
    parent_task_id: int | None = None
    granularity: Granularity
    title: str = Field(min_length=1, max_length=256)
    priority: int = Field(default=2, ge=1, le=3)
    estimate_hours: float | None = None
    due_date: dt.date | None = None


class TaskUpdateIn(BaseModel):
    title: str | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    due_date: dt.date | None = None
    status: TaskStatus | None = None
    order: int | None = None


class ActionIn(BaseModel):
    task_id: int | None = None
    title: str = Field(min_length=1, max_length=256)
    minutes: int | None = Field(default=None, ge=0, le=240)  # 0/None = 不限时(如"7点起床")
    date: dt.date


class ActionUpdateIn(BaseModel):
    title: str | None = None
    minutes: int | None = Field(default=None, ge=0, le=240)
    date: dt.date | None = None


class ActionOut(BaseModel):
    id: int
    task_id: int | None
    title: str
    minutes: int
    date: dt.date
    status: str
    done_at: dt.datetime | None
    postpone_count: int


def _action_out(a: Action) -> ActionOut:
    return ActionOut(
        id=a.id, task_id=a.task_id, title=a.title, minutes=a.minutes, date=a.date,
        status=a.status.value, done_at=a.done_at, postpone_count=a.postpone_count,
    )


async def _owned(db: AsyncSession, model, id_: int, user: User):
    obj = (
        await db.execute(select(model).where(model.id == id_, model.user_id == user.id))
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return obj


async def _rollover(db: AsyncSession, user: User) -> int:
    """Lazy rollover (P0-6): yesterday-and-older open actions -> +1 day;
    postpone_count >= 3 -> debt. Returns moved count."""
    today = dt.date.today()
    moved = 0
    overdue = (
        await db.execute(
            select(Action).where(
                Action.user_id == user.id,
                Action.status.in_([ActionStatus.open, ActionStatus.debt]),
                Action.date < today,
            )
        )
    ).scalars().all()
    for a in overdue:
        if a.status == ActionStatus.debt:
            continue
        a.postpone_count += 1
        a.date = today
        if a.postpone_count >= POSTPONE_LIMIT:
            a.status = ActionStatus.debt
        moved += 1
    if moved:
        await db.commit()
    return moved


# ---------- goals ----------

def _goal_progress(
    db: AsyncSession,
    goal: Goal,
    tasks_by_goal: dict[int, list[Task]],
    actions_by_task: dict[int | None, list[Action]] | None = None,
) -> float:
    """Read-only computed progress (P1-1): leaf task completion rate; a leaf
    with no sub-tasks counts its own actions completion (fallback task status)."""
    tasks = tasks_by_goal.get(goal.id, [])
    by_parent: dict[int | None, list[Task]] = {}
    for t in tasks:
        by_parent.setdefault(t.parent_task_id, []).append(t)
    actions_by_task = actions_by_task or {}

    def rate(parent_id: int | None) -> float:
        kids = by_parent.get(parent_id, [])
        if not kids:
            return 0.0
        vals = []
        for k in kids:
            if k.status == TaskStatus.done:
                vals.append(1.0)
                continue
            sub = rate(k.id)
            if sub > 0.0:
                vals.append(sub)
                continue
            acts = actions_by_task.get(k.id, [])
            if acts:
                vals.append(sum(1 for a in acts if a.status == ActionStatus.done) / len(acts))
            else:
                vals.append(0.0)
        return sum(vals) / len(vals)

    return round(rate(None), 3)


@router.post("/goals")
async def create_goal(
    body: GoalIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    g = Goal(user_id=user.id, **body.model_dump())
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return {"id": g.id, **body.model_dump(mode="json"), "status": g.status.value}


@router.get("/goals")
async def list_goals(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    goals = (
        await db.execute(select(Goal).where(Goal.user_id == user.id).order_by(Goal.created_at.desc()))
    ).scalars().all()
    tasks = (
        await db.execute(select(Task).where(Task.user_id == user.id))
    ).scalars().all()
    actions = (
        await db.execute(select(Action).where(Action.user_id == user.id))
    ).scalars().all()
    by_goal: dict[int, list[Task]] = {}
    acts_by_task: dict[int | None, list[Action]] = {}
    for t in tasks:
        if t.goal_id:
            by_goal.setdefault(t.goal_id, []).append(t)
    for a in actions:
        acts_by_task.setdefault(a.task_id, []).append(a)
    return [
        {
            "id": g.id,
            "title": g.title,
            "description": g.description,
            "category": g.category,
            "dimension": g.dimension,
            "deadline": g.deadline.isoformat() if g.deadline else None,
            "status": g.status.value,
            "progress": _goal_progress(db, g, by_goal, acts_by_task),
            "task_count": len(by_goal.get(g.id, [])),
        }
        for g in goals
    ]


@router.put("/goals/{goal_id}")
async def update_goal(
    goal_id: int,
    body: GoalUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    g = await _owned(db, Goal, goal_id, user)
    for k, v in body.model_dump(exclude_unset=True, mode="json").items():
        setattr(g, k, v)
    await db.commit()
    return {"ok": True}


@router.delete("/goals/{goal_id}")
async def delete_goal(
    goal_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    g = await _owned(db, Goal, goal_id, user)
    await db.delete(g)
    await db.commit()
    return {"ok": True}


# ---------- tasks ----------

@router.post("/tasks")
async def create_task(
    body: TaskIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if body.goal_id:
        await _owned(db, Goal, body.goal_id, user)
    goal_id = body.goal_id
    if body.parent_task_id:
        parent = await _owned(db, Task, body.parent_task_id, user)
        order_rank = {Granularity.year: 0, Granularity.month: 1, Granularity.week: 2}
        if order_rank[body.granularity] <= order_rank[parent.granularity]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Child granularity must be finer than parent")
        if goal_id is None:
            goal_id = parent.goal_id  # inherit goal from parent chain
    t = Task(user_id=user.id, goal_id=goal_id, **{k: v for k, v in body.model_dump().items() if k != "goal_id"})
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return {"id": t.id, **body.model_dump(mode="json"), "status": t.status.value}


@router.get("/tasks")
async def list_tasks(
    goal_id: int | None = None,
    granularity: Granularity | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Task).where(Task.user_id == user.id)
    if goal_id:
        q = q.where(Task.goal_id == goal_id)
    if granularity:
        q = q.where(Task.granularity == granularity)
    q = q.order_by(Task.priority, Task.order)
    tasks = (await db.execute(q)).scalars().all()
    actions = (
        await db.execute(select(Action).where(Action.user_id == user.id))
    ).scalars().all()
    acts_by_task: dict[int | None, list[Action]] = {}
    for a in actions:
        acts_by_task.setdefault(a.task_id, []).append(a)

    def task_progress(t: Task) -> float:
        kids = acts_by_task.get(t.id, [])
        if not kids:
            return 1.0 if t.status == TaskStatus.done else 0.0
        return round(sum(1 for a in kids if a.status == ActionStatus.done) / len(kids), 3)

    return [
        {
            "id": t.id,
            "goal_id": t.goal_id,
            "parent_task_id": t.parent_task_id,
            "granularity": t.granularity.value,
            "title": t.title,
            "priority": t.priority,
            "estimate_hours": t.estimate_hours,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "status": t.status.value,
            "order": t.order,
            "progress": task_progress(t),
        }
        for t in tasks
    ]


@router.put("/tasks/{task_id}")
async def update_task(
    task_id: int,
    body: TaskUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    t = await _owned(db, Task, task_id, user)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] == TaskStatus.done and t.status != TaskStatus.done:
        t.completed_at = utcnow()
    for k, v in data.items():
        setattr(t, k, v)
    await db.commit()
    return {"ok": True}


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    t = await _owned(db, Task, task_id, user)
    await db.delete(t)
    await db.commit()
    return {"ok": True}


class GenChildrenIn(BaseModel):
    profile_summary: str | None = None


def _fallback_month_plan(parent_title: str, months: int) -> list[dict]:
    """Progressive monthly plan (foundation -> advancement -> sprint) without LLM."""
    phases = []
    for i in range(1, months + 1):
        pct = round(i / months * 100)
        if i == 1 or months <= 2 and i == 1:
            stage = "打基础:了解全貌、准备资源、建立习惯"
        elif i / months < 0.34:
            stage = "基础期:完成入门内容,建立节奏"
        elif i / months < 0.75:
            stage = "进阶期:加大投入,攻克核心难点"
        else:
            stage = "冲刺期:强化实战、查漏补缺、验收成果"
        hours = 6 + round(i / months * 12)
        phases.append({
            "month_offset": i,
            "title": f"第{i}月:{stage},累计进度约 {pct}%",
            "priority": 1 if i / months >= 0.75 else 2,
            "estimate_hours": hours,
        })
    return phases


@router.post("/tasks/{task_id}/decompose")
async def decompose_task(
    task_id: int,
    body: GenChildrenIn | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Progressive split (redesigned):
    - year task -> MONTHLY PROGRESS PLAN: one month task per month until the
      task's due date (max 12), each stating that month's stage outcome and
      cumulative progress;
    - month task -> week tasks that concretize the month plan.
    Children are a concrete refinement of the parent, never duplicates."""
    t = await _owned(db, Task, task_id, user)
    child_gran = {"year": Granularity.month, "month": Granularity.week}.get(t.granularity)
    if child_gran is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Week tasks are decomposed into actions, not tasks")
    goal_title = ""
    if t.goal_id:
        g = await db.get(Goal, t.goal_id)
        goal_title = g.title if g else ""

    from ..services import llm as llm_svc

    profile = body.profile_summary if body else None
    start = dt.date.today()
    if t.due_date:
        due = t.due_date.date() if hasattr(t.due_date, "date") else t.due_date
    else:
        due = start.replace(month=12, day=1) if t.granularity == Granularity.year else start + dt.timedelta(weeks=4)

    created = []
    degraded = False

    if t.granularity == Granularity.year:
        # ---- monthly progress plan: from NOW to the expected completion date,
        #循序渐进 (foundation -> advancement -> sprint) ----
        months = max(1, min(12, (due.year - start.year) * 12 + (due.month - start.month) + 1))
        try:
            plan = await llm_svc.generate_month_plan(
                db, goal_title or t.title, t.title, months, profile or ""
            )
            degraded = False
        except llm_svc.LLMUnavailable:
            plan = _fallback_month_plan(t.title, months)
            degraded = True
        for item in plan[:months]:
            offset = int(item.get("month_offset") or len(created) + 1)
            month_date = start.replace(day=1) + dt.timedelta(days=30 * (offset - 1))
            ct = Task(
                user_id=user.id, goal_id=t.goal_id, parent_task_id=t.id,
                granularity=Granularity.month,
                title=item.get("title") or f"第{offset}月阶段成果",
                priority=item.get("priority", 2), estimate_hours=item.get("estimate_hours"),
                due_date=month_date, order=offset,
            )
            db.add(ct)
            created.append(ct)
    else:
        # ---- month -> week tasks (unchanged logic) ----
        try:
            children = await llm_svc.generate_tasks(
                db, goal_title or t.title, "", child_gran.value, profile or "", parent_context=t.title
            )
            degraded = False
        except llm_svc.LLMUnavailable:
            children = llm_svc.fallback_tasks(goal_title or t.title, child_gran.value)
            degraded = True
        for c in children:
            ct = Task(
                user_id=user.id, goal_id=t.goal_id, parent_task_id=t.id,
                granularity=child_gran, title=c.get("title", ""),
                priority=c.get("priority", 2), estimate_hours=c.get("estimate_hours"),
            )
            db.add(ct)
            created.append(ct)

    await db.commit()
    return {
        "children": [
            {"id": c.id, "title": c.title, "granularity": c.granularity.value,
             "due_date": c.due_date.isoformat() if c.due_date else None}
            for c in created
        ],
        "degraded": degraded,
    }


# ---------- actions ----------

@router.post("/actions", response_model=ActionOut)
async def create_action(
    body: ActionIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if body.task_id:
        await _owned(db, Task, body.task_id, user)
    a = Action(user_id=user.id, status=ActionStatus.open, minutes=body.minutes or 0, **{k: v for k, v in body.model_dump().items() if k != "minutes"})
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return _action_out(a)


@router.get("/actions", response_model=list[ActionOut])
async def list_actions(
    date: dt.date | None = None,
    status: ActionStatus | None = None,
    task_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _rollover(db, user)  # lazy rollover on read (P0-6)
    q = select(Action).where(Action.user_id == user.id)
    if date:
        q = q.where(Action.date == date)
    if status:
        q = q.where(Action.status == status)
    if task_id:
        q = q.where(Action.task_id == task_id)
    q = q.order_by(Action.date, Action.id)
    return [_action_out(a) for a in (await db.execute(q)).scalars().all()]


@router.put("/actions/{action_id}", response_model=ActionOut)
async def update_action(
    action_id: int,
    body: ActionUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    a = await _owned(db, Action, action_id, user)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    await db.commit()
    await db.refresh(a)
    return _action_out(a)


@router.delete("/actions/{action_id}")
async def delete_action(
    action_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Remove a todo entirely (user-added items or unwanted auto-generated ones)."""
    a = await _owned(db, Action, action_id, user)
    await db.delete(a)
    await db.commit()
    return {"ok": True}


@router.post("/actions/{action_id}/complete", response_model=ActionOut)
async def complete_action(
    action_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    a = await _owned(db, Action, action_id, user)
    a.status = ActionStatus.done
    a.done_at = utcnow()  # single source of truth for stats (P0-3)
    await db.commit()
    await db.refresh(a)
    return _action_out(a)


@router.post("/actions/{action_id}/reopen", response_model=ActionOut)
async def reopen_action(
    action_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Undo completion: revert status, no history log (v1 simplification, P0-3)."""
    a = await _owned(db, Action, action_id, user)
    a.status = ActionStatus.open
    a.done_at = None
    await db.commit()
    await db.refresh(a)
    return _action_out(a)


@router.post("/actions/{action_id}/debt/{op}", response_model=ActionOut)
async def debt_operation(
    action_id: int,
    op: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Debt actions: do-today / give-up (P0-6)."""
    a = await _owned(db, Action, action_id, user)
    if a.status != ActionStatus.debt:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Action is not in debt state")
    if op == "do":
        a.status = ActionStatus.open
        a.postpone_count = 0
        a.date = dt.date.today()
    elif op == "giveup":
        a.status = ActionStatus.given_up
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "op must be 'do' or 'giveup'")
    await db.commit()
    await db.refresh(a)
    return _action_out(a)


@router.get("/today")
async def today(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Today view: today's open actions + debts + summary counters.
    Lazy catch-up: if the 02:00 auto-plan hasn't run today and it's past 02:00,
    run it on first open (design: daily 02:00 auto split)."""
    from ..models import AutoPlanLog

    today_d = dt.date.today()
    logged = (
        await db.execute(
            select(AutoPlanLog).where(
                AutoPlanLog.user_id == user.id, AutoPlanLog.plan_date == today_d
            )
        )
    ).scalar_one_or_none()
    if logged is None and dt.datetime.now().hour >= 2:
        has_tasks = (
            await db.execute(
                select(Task.id).where(Task.user_id == user.id, Task.status != TaskStatus.done).limit(1)
            )
        ).scalar_one_or_none()
        if has_tasks:
            try:
                await run_auto_plan(db, user, manual=False)
            except Exception:
                pass  # never block the today view on planner failure
    await _rollover(db, user)
    actions = (
        await db.execute(
            select(Action).where(
                Action.user_id == user.id, Action.date == today_d
            )
        )
    ).scalars().all()
    debts = (
        await db.execute(
            select(Action).where(Action.user_id == user.id, Action.status == ActionStatus.debt)
        )
    ).scalars().all()
    done = [a for a in actions if a.status == ActionStatus.done]
    focus = sum(a.minutes for a in done)
    return {
        "date": today_d.isoformat(),
        "actions": [_action_out(a).model_dump(mode="json") for a in actions],
        "debts": [_action_out(a).model_dump(mode="json") for a in debts],
        "summary": {
            "total": len(actions),
            "done": len(done),
            "focus_minutes": focus,
        },
    }


# ---------- board ----------

@router.post("/today/auto-plan")
async def auto_plan_today(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Manual trigger of the auto-plan (same logic as the 02:00 scheduler)."""
    result = await run_auto_plan(db, user, manual=True)
    return result


async def run_auto_plan(db: AsyncSession, user: User, manual: bool = False) -> dict:
    """Auto-generate today's actions from tasks (需求 #1): pick candidate tasks
    (week tasks first, then month/year if no week tasks; doing or due soon),
    split each into actions, and schedule the first action for today.
    Tasks that already have an action today are skipped to avoid duplicates.
    Runs once per user per day (AutoPlanLog); manual runs bypass the marker."""
    from ..models import AutoPlanLog
    from ..services import llm as llm_svc

    today = dt.date.today()
    if not manual:
        logged = (
            await db.execute(
                select(AutoPlanLog).where(
                    AutoPlanLog.user_id == user.id, AutoPlanLog.plan_date == today
                )
            )
        ).scalar_one_or_none()
        if logged:
            return {"created": [], "skipped_existing": 0, "degraded": False, "already_ran": True}

    await _rollover(db, user)

    tasks = (
        await db.execute(
            select(Task).where(
                Task.user_id == user.id,
                Task.status != TaskStatus.done,
            )
        )
    ).scalars().all()
    existing = (
        await db.execute(
            select(Action).where(Action.user_id == user.id, Action.date == today)
        )
    ).scalars().all()
    tasks_with_action_today = {a.task_id for a in existing}

    # preference: week -> month -> year, doing before backlog, nearer due first
    rank = {Granularity.week: 0, Granularity.month: 1, Granularity.year: 2}
    candidates = sorted(
        [t for t in tasks if t.id not in tasks_with_action_today],
        key=lambda t: (
            rank[t.granularity],
            0 if t.status == TaskStatus.doing else 1,
            t.due_date.date() if t.due_date else dt.date.max,
        ),
    )[:5]

    created = []
    degraded = False
    for t in candidates:
        try:
            acts = await llm_svc.generate_actions(db, t.title, None)
        except llm_svc.LLMUnavailable:
            acts = [
                {"title": f"推进:{t.title[:24]}", "minutes": 30},
                {"title": f"收尾:{t.title[:24]}", "minutes": 20},
            ]
            degraded = True
        first = acts[0] if acts else {"title": f"推进:{t.title[:24]}", "minutes": 30}
        a = Action(
            user_id=user.id, task_id=t.id,
            title=first.get("title") or f"推进:{t.title[:24]}",
            minutes=int(first.get("minutes") or 30),
            date=today, status=ActionStatus.open,
        )
        db.add(a)
        created.append(a)
    db.add(AutoPlanLog(user_id=user.id, plan_date=today, created_count=len(created)))
    if created or not manual:
        await db.commit()
    return {
        "created": [
            {"id": a.id, "title": a.title, "minutes": a.minutes, "task_id": a.task_id}
            for a in created
        ],
        "skipped_existing": len(tasks_with_action_today),
        "degraded": degraded,
    }


def _derive_status(own: TaskStatus, children_status: list[TaskStatus]) -> TaskStatus:
    """Parent status derived from children (需求): all done -> done;
    any doing/done -> doing; else backlog."""
    if not children_status:
        return own
    if all(s == TaskStatus.done for s in children_status):
        return TaskStatus.done
    if any(s in (TaskStatus.doing, TaskStatus.done) for s in children_status):
        return TaskStatus.doing
    return TaskStatus.backlog


@router.get("/board")
async def board(
    dimension: str = Query(default="week", pattern="^(goal|sub|month|week)$"),
    goal_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Kanban by dimension: 目标 / 子目标 / 月度进度规划 / 周任务.
    Upper-layer statuses are derived from lower layers (需求)."""
    from ..models import Goal as GoalModel, GoalStatus

    all_tasks = (
        await db.execute(select(Task).where(Task.user_id == user.id))
    ).scalars().all()
    actions = (
        await db.execute(select(Action).where(Action.user_id == user.id))
    ).scalars().all()
    acts_by_task: dict[int | None, list[Action]] = {}
    for a in actions:
        acts_by_task.setdefault(a.task_id, []).append(a)
    tasks_by_id = {t.id: t for t in all_tasks}
    children: dict[int | None, list[Task]] = {}
    for t in all_tasks:
        children.setdefault(t.parent_task_id, []).append(t)

    def eff_status(t: Task) -> TaskStatus:
        kids = children.get(t.id, [])
        if kids:
            return _derive_status(t.status, [eff_status(k) for k in kids])
        if t.status == TaskStatus.done:
            return TaskStatus.done  # manual completion wins
        # leaf: derive from its actions (待办完成情况)
        acts = acts_by_task.get(t.id, [])
        if acts:
            done = sum(1 for a in acts if a.status == ActionStatus.done)
            if done == len(acts):
                return TaskStatus.done
            if done > 0:
                return TaskStatus.doing
        return t.status

    def card(t: Task, derived: bool) -> dict:
        kids = acts_by_task.get(t.id, [])
        prog = (
            round(sum(1 for a in kids if a.status == ActionStatus.done) / len(kids), 3)
            if kids
            else (1.0 if t.status == TaskStatus.done else 0.0)
        )
        parent = tasks_by_id.get(t.parent_task_id)
        return {
            "id": t.id,
            "title": t.title,
            "goal_id": t.goal_id,
            "parent_title": parent.title if parent else None,
            "priority": t.priority,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "progress": prog,
            "derived": derived,
        }

    if dimension == "goal":
        goals = (
            await db.execute(
                select(GoalModel).where(
                    GoalModel.user_id == user.id, GoalModel.status == GoalStatus.active
                )
            )
        ).scalars().all()
        by_goal: dict[int | None, list[Task]] = {}
        for t in all_tasks:
            if t.granularity == Granularity.year and not t.parent_task_id:
                by_goal.setdefault(t.goal_id, []).append(t)

        def goal_eff(g: GoalModel) -> TaskStatus:
            subs = by_goal.get(g.id, [])
            return _derive_status(
                TaskStatus.done if g.status == GoalStatus.done else TaskStatus.backlog,
                [eff_status(s) for s in subs],
            )

        columns: dict[str, list] = {"backlog": [], "doing": [], "done": []}
        col_of = {TaskStatus.backlog: "backlog", TaskStatus.doing: "doing", TaskStatus.done: "done"}
        for g in goals:
            st = goal_eff(g)
            columns[col_of[st]].append({
                "id": g.id, "title": g.title, "goal_id": g.id,
                "priority": 2, "due_date": g.deadline.isoformat() if g.deadline else None,
                "progress": _goal_progress(db, g, by_goal, acts_by_task), "derived": True,
            })
        return {"dimension": "goal", "columns": columns}

    gran = {"sub": Granularity.year, "month": Granularity.month, "week": Granularity.week}[dimension]
    q = select(Task).where(Task.user_id == user.id, Task.granularity == gran)
    if goal_id:
        q = q.where(Task.goal_id == goal_id)
    q = q.order_by(Task.priority, Task.order)
    items = (await db.execute(q)).scalars().all()

    columns = {"backlog": [], "doing": [], "done": []}
    for t in items:
        st = eff_status(t)
        has_children = bool(children.get(t.id))
        columns[st.value].append({**card(t, has_children), "derived_status": st.value if has_children else None})
    return {"dimension": dimension, "columns": columns}

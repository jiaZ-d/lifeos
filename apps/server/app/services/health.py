"""Health baseline estimation from record fields (design §3.2 input #4)."""
from __future__ import annotations

import statistics
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Entry, EntryCategory


def _num(extra: dict | None, *keys: str) -> float | None:
    if not extra:
        return None
    for k in keys:
        v = extra.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


async def estimate_health(db: AsyncSession, user_id: int, days: int = 90) -> dict:
    """Rule-based baseline from exercise/routine/diet records -> 10y outlook band."""
    entries = (
        await db.execute(
            select(Entry).where(
                Entry.user_id == user_id,
                Entry.is_private == False,  # noqa: E712
                Entry.primary_category.in_(
                    [EntryCategory.exercise, EntryCategory.routine, EntryCategory.diet]
                ),
            )
        )
    ).scalars().all()

    exercise_minutes = 0.0
    high_intensity = 0
    sleep_hours: list[float] = []
    diet_scores: list[float] = []
    for e in entries:
        extra = e.extra_json or {}
        if e.primary_category == EntryCategory.exercise:
            m = _num(extra, "minutes", "duration", "时长")
            exercise_minutes += m if m is not None else 30.0
            if str(extra.get("intensity", extra.get("强度", ""))) in ("high", "高"):
                high_intensity += 1
        elif e.primary_category == EntryCategory.routine:
            s = _num(extra, "sleep_hours", "睡眠时长", "sleep")
            if s is not None:
                sleep_hours.append(s)
        elif e.primary_category == EntryCategory.diet:
            d = _num(extra, "health", "健康度")
            if d is not None:
                diet_scores.append(d)

    n = max(1, days / 7)
    weekly_exercise = exercise_minutes / n  # minutes per week over window
    avg_sleep = statistics.mean(sleep_hours) if sleep_hours else None
    avg_diet = statistics.mean(diet_scores) if diet_scores else None

    score = 5.0
    score += min(3.0, weekly_exercise / 45)          # up to +3: >=135min/week
    score -= max(1.5, (abs(avg_sleep - 7.5)) * 1.5) if avg_sleep else 0.0
    score += (avg_diet - 3) * 0.8 if avg_diet is not None else 0.0
    score += 0.3 if high_intensity >= 4 else 0.0
    score = max(1.0, min(10.0, round(score, 1)))

    if score >= 7:
        outlook = "体能保持良好,慢病风险低于同龄平均"
    elif score >= 4.5:
        outlook = "体能缓慢下降,慢病风险为平均水平,可通过规律锻炼改善"
    else:
        outlook = "体能下降较快,建议尽快建立锻炼与作息习惯,关注心血管与代谢指标"

    return {
        "score": score,
        "weekly_exercise_minutes": round(weekly_exercise),
        "avg_sleep_hours": round(avg_sleep, 1) if avg_sleep else None,
        "avg_diet_health": round(avg_diet, 1) if avg_diet is not None else None,
        "outlook_10y": outlook,
        "sample_size": len(entries),
    }

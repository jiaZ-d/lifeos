"""User data scoping + AI authorization rules (design P0-5 / P1-7).

Authorization is the INTERSECTION of:
  - category-level opt-in (privacy_settings.ai_allowed; None -> default rule:
    social categories excluded, everything else allowed)
  - entry-level opt-in (entries.ai_allowed)
Private (encrypted) entries never enter LLM context.
All LLM context assembly must go through `ai_visible_entries`.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Entry, EntryCategory, PrivacySetting

DEFAULT_AI_EXCLUDED = {EntryCategory.social}


async def category_ai_allowed(db: AsyncSession, user_id: int, category: EntryCategory) -> bool:
    row = (
        await db.execute(
            select(PrivacySetting).where(
                PrivacySetting.user_id == user_id, PrivacySetting.category == category
            )
        )
    ).scalar_one_or_none()
    if row is None or row.ai_allowed is None:
        return category not in DEFAULT_AI_EXCLUDED
    return bool(row.ai_allowed)


async def ai_visible_entries(db: AsyncSession, user_id: int) -> list[Entry]:
    """Entries allowed into LLM context for a user (intersection rule, P0-5)."""
    entries = (
        await db.execute(
            select(Entry).where(
                Entry.user_id == user_id,
                Entry.is_private == False,  # noqa: E712
                Entry.ai_allowed == True,  # noqa: E712
            )
        )
    ).scalars().all()
    allowed: list[Entry] = []
    for e in entries:
        if await category_ai_allowed(db, user_id, e.primary_category):
            allowed.append(e)
    return allowed

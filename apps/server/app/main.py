"""LifeOS FastAPI entry point."""
import asyncio
import datetime as dt
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from .config import settings
from .db import init_db, SessionLocal
from .api import auth as auth_router
from .api import entries as entries_router
from .api import knowledge as knowledge_router
from .api import llm as llm_router
from .api import projections as projections_router
from .api import stats as stats_router
from .api import tasks as tasks_router
from .api import timeline as timeline_router
from .models import User

log = logging.getLogger("lifeos.scheduler")

DIST_DIR = Path(__file__).resolve().parent.parent.parent / "web" / "dist"


def due_jobs(now: dt.datetime) -> list[str]:
    """Pure helper (P1-6): which daily jobs should run at `now`."""
    jobs = []
    if now.hour == 1 and now.minute == 0:
        jobs.append("prev_summary")
    if now.hour == 2 and now.minute == 0:
        jobs.append("auto_plan")
    if now.hour == settings.daily_summary_hour and now.minute == settings.daily_summary_minute:
        jobs.append("today_summary")
    return jobs


async def run_daily_jobs(now: dt.datetime) -> dict:
    """Execute the jobs that are due at `now`, once per job per day (P1-6).
    Uses the current appdb.SessionLocal binding (test-friendly)."""
    from . import db as appdb

    ran = {}
    async with appdb.SessionLocal() as db:
        if "prev_summary" in due_jobs(now):
            from .api.llm import ensure_daily_summary

            users = (await db.execute(select(User))).scalars().all()
            yesterday = now.date() - dt.timedelta(days=1)
            for u in users:
                try:
                    await ensure_daily_summary(db, u, yesterday)
                    ran.setdefault("prev_summary", []).append(u.id)
                except Exception as exc:
                    log.warning("prev-day summary failed for user %s: %s", u.id, exc)
        if "auto_plan" in due_jobs(now):
            users = (await db.execute(select(User))).scalars().all()
            for u in users:
                try:
                    res = await tasks_router.run_auto_plan(db, u, manual=False)
                    if res.get("created"):
                        ran.setdefault("auto_plan", []).append(u.id)
                except Exception as exc:
                    log.warning("auto-plan failed for user %s: %s", u.id, exc)
        if "today_summary" in due_jobs(now):
            ran["today_summary"] = []  # lazy catch-up path handles per-user
        # P2-2: purge expired llm_cache rows once a day
        from .models import LLMCache

        await db.execute(
            sa_delete(LLMCache).where(
                LLMCache.created_at < dt.datetime.now().astimezone() - dt.timedelta(hours=settings.llm_cache_hours)
            )
        )
        await db.commit()
    return ran


async def daily_scheduler():
    """Local-time daily jobs (loop checks every 60s). Logic lives in
    run_daily_jobs/due_jobs so it stays unit-testable (P1-6)."""
    jobs_done: dict[str, dt.date] = {}
    while True:
        try:
            now = dt.datetime.now()
            for job in due_jobs(now):
                if jobs_done.get(job) != now.date():
                    jobs_done[job] = now.date()
                    ran = await run_daily_jobs(now)
                    log.info("daily job %s ran: %s", job, ran)
        except Exception as exc:
            log.warning("scheduler tick failed: %s", exc)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler = asyncio.create_task(daily_scheduler())
    yield
    scheduler.cancel()


app = FastAPI(title="LifeOS", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(entries_router.router)
app.include_router(tasks_router.router)
app.include_router(llm_router.router)
app.include_router(projections_router.router)
app.include_router(stats_router.router)
app.include_router(timeline_router.router)
app.include_router(knowledge_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": "LifeOS", "version": "1.0.0"}


# Serve built frontend (single-port mode)
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        target = DIST_DIR / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST_DIR / "index.html")

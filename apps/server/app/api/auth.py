"""Auth & security routes: register/login, PIN setup/verify/change, admin recovery (N1-N3)."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas
from ..auth import create_token, get_admin_user, get_current_user
from ..db import get_db
from ..models import User, UserKeys
from ..services import crypto

router = APIRouter(prefix="/api/auth", tags=["auth"])

# N3: brute-force protection shared by login / pin verify / recover
_FAILS: dict[str, list[float]] = {}
LOCK_WINDOW = 300  # seconds
MAX_FAILS = 5


def _check_lock(key: str) -> None:
    now = time.time()
    fails = [t for t in _FAILS.get(key, []) if now - t < LOCK_WINDOW]
    _FAILS[key] = fails
    if len(fails) >= MAX_FAILS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, locked for 5 minutes")


def _record_fail(key: str) -> None:
    _FAILS.setdefault(key, []).append(time.time())


def _clear(key: str) -> None:
    _FAILS.pop(key, None)


async def _first_user_is_admin(db: AsyncSession) -> bool:
    return (await db.execute(select(User.id).limit(1))).scalar_one_or_none() is None


@router.post("/register", response_model=schemas.TokenOut)
async def register(body: schemas.RegisterIn, db: AsyncSession = Depends(get_db)):
    exists = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    user = User(
        username=body.username,
        password_hash=crypto.hash_password(body.password),
        is_admin=await _first_user_is_admin(db),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return schemas.TokenOut(
        token=create_token(user.id), user_id=user.id, username=user.username, is_admin=user.is_admin
    )


@router.post("/login", response_model=schemas.TokenOut)
async def login(body: schemas.LoginIn, db: AsyncSession = Depends(get_db)):
    _check_lock(f"login:{body.username}")
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None or not crypto.verify_password(body.password, user.password_hash):
        _record_fail(f"login:{body.username}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    _clear(f"login:{body.username}")
    return schemas.TokenOut(
        token=create_token(user.id), user_id=user.id, username=user.username, is_admin=user.is_admin
    )


# ---------- PIN / KEK-DEK ----------

async def _get_keys(db: AsyncSession, user_id: int) -> UserKeys:
    keys = (await db.execute(select(UserKeys).where(UserKeys.user_id == user_id))).scalar_one_or_none()
    if keys is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PIN not set up yet")
    return keys


@router.get("/pin/status")
async def pin_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    keys = (
        await db.execute(select(UserKeys).where(UserKeys.user_id == user.id))
    ).scalar_one_or_none()
    return {
        "exists": keys is not None,
        "recovery_enabled": bool(keys and keys.admin_wrapped_dek),
        "is_admin": user.is_admin,
    }


@router.post("/pin/setup")
async def pin_setup(
    body: schemas.PinSetupIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    crypto.validate_pin(body.pin)
    existing = (
        await db.execute(select(UserKeys).where(UserKeys.user_id == user.id))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "PIN already set")
    dek = crypto.generate_dek()
    wrapped, kek_salt = crypto.wrap_dek(dek, body.pin)
    vsalt, vhash = crypto.make_pin_verify(body.pin)
    db.add(
        UserKeys(
            user_id=user.id,
            wrapped_dek=wrapped,
            kek_salt=kek_salt,
            pin_verify_salt=vsalt,
            pin_verify_hash=vhash,
        )
    )
    await db.commit()
    return {"ok": True}


@router.post("/pin/verify")
async def pin_verify(
    body: schemas.PinVerifyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    keys = await _get_keys(db, user.id)
    _check_lock(f"pin:{user.id}")
    ok = crypto.verify_pin(body.pin, keys.pin_verify_salt, keys.pin_verify_hash)
    if not ok:
        _record_fail(f"pin:{user.id}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong PIN")
    _clear(f"pin:{user.id}")
    dek = crypto.unwrap_dek(keys.wrapped_dek, body.pin, keys.kek_salt)
    # Session DEK is held in memory server-side per user for the request lifetime;
    # v1 local single-user: return nothing, endpoints requiring decryption take pin.
    return {"ok": True}


@router.put("/pin")
async def pin_change(
    body: schemas.PinChangeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change PIN: unwrap DEK with old pin (or admin recovery path), re-wrap only."""
    keys = await _get_keys(db, user.id)
    if body.old_pin is not None:
        if not crypto.verify_pin(body.old_pin, keys.pin_verify_salt, keys.pin_verify_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong old PIN")
        dek = crypto.unwrap_dek(keys.wrapped_dek, body.old_pin, keys.kek_salt)
    else:
        if not user.is_admin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "old_pin required")
        # admin reset via own password requires recovery passphrase; handled in /pin/recover
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use /pin/recover without old PIN")
    crypto.validate_pin(body.new_pin)
    keys.wrapped_dek, keys.kek_salt = crypto.wrap_dek(dek, body.new_pin)
    keys.pin_verify_salt, keys.pin_verify_hash = crypto.make_pin_verify(body.new_pin)
    await db.commit()
    return {"ok": True}


@router.post("/pin/recover/{target_username}")
async def pin_recover_target(
    target_username: str,
    body: schemas.PinRecoverIn,
    db: AsyncSession = Depends(get_db),
):
    _check_lock(f"recover:{body.username}")
    admin = (
        await db.execute(
            select(User).where(User.username == body.username, User.is_admin == True)  # noqa: E712
        )
    ).scalar_one_or_none()
    if admin is None or not crypto.verify_password(body.admin_password, admin.password_hash):
        _record_fail(f"recover:{body.username}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid admin credentials")
    target = (
        await db.execute(select(User).where(User.username == target_username))
    ).scalar_one_or_none()
    keys = (
        await db.execute(select(UserKeys).where(UserKeys.user_id == target.id))
    ).scalar_one_or_none() if target else None
    if target is None or keys is None or not keys.admin_wrapped_dek or not keys.admin_kek_salt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recovery not available for this user")
    try:
        dek = crypto.unwrap_dek(keys.admin_wrapped_dek, body.recovery_passphrase, keys.admin_kek_salt)
    except Exception:
        _record_fail(f"recover:{body.username}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong recovery passphrase")
    crypto.validate_pin(body.new_pin)
    keys.wrapped_dek, keys.kek_salt = crypto.wrap_dek(dek, body.new_pin)
    keys.pin_verify_salt, keys.pin_verify_hash = crypto.make_pin_verify(body.new_pin)
    await db.commit()
    _clear(f"recover:{body.username}")
    return {"ok": True, "recovered_for": target_username}


class _RecoveryWrapIn(schemas.PinVerifyIn):
    recovery_passphrase: str = Field(min_length=8, max_length=128)


@router.post("/pin/recovery-wrap")
async def set_recovery_wrap(
    body: _RecoveryWrapIn,
    user: User = Depends(get_current_user),
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """(Re)set the admin recovery wrap — ADMIN ONLY (BUG-01 越权修复).
    Verifies the target user's PIN (to unwrap DEK), wraps under the recovery
    passphrase (decoupled from login password, N1)."""
    keys = await _get_keys(db, user.id)
    if not crypto.verify_pin(body.pin, keys.pin_verify_salt, keys.pin_verify_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong PIN")
    dek = crypto.unwrap_dek(keys.wrapped_dek, body.pin, keys.kek_salt)
    keys.admin_wrapped_dek, keys.admin_kek_salt = crypto.wrap_dek(dek, body.recovery_passphrase)
    await db.commit()
    return {"ok": True}


@router.delete("/pin/recovery-wrap")
async def opt_out_recovery(
    user: User = Depends(get_current_user),
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Disable admin recovery — ADMIN ONLY (BUG-01 越权修复)."""
    keys = await _get_keys(db, user.id)
    keys.admin_wrapped_dek = None
    keys.admin_kek_salt = None
    await db.commit()
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"user_id": user.id, "username": user.username, "is_admin": user.is_admin}


# ---------- admin: user management ----------

@router.get("/users")
async def list_users(admin: User = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    users = (await db.execute(select(User).order_by(User.id))).scalars().all()
    return [
        {
            "id": u.id, "username": u.username, "is_admin": u.is_admin,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


async def _delete_user_data(db: AsyncSession, user_id: int) -> None:
    """Remove a user and all their business data (design: per-user isolation)."""
    from sqlalchemy import delete as sa_delete

    from ..models import (
        Action, AutoPlanLog, DailySummary, Entry, Goal, LLMCache, PrivacySetting,
        Projection, Report, Task, UserKeys,
    )

    task_ids = (await db.execute(select(Task.id).where(Task.user_id == user_id))).scalars().all()
    goal_ids = (await db.execute(select(Goal.id).where(Goal.user_id == user_id))).scalars().all()
    await db.execute(sa_delete(Action).where(Action.user_id == user_id))
    if task_ids:
        await db.execute(sa_delete(Task).where(Task.id.in_(task_ids)))
    await db.execute(sa_delete(Task).where(Task.user_id == user_id))
    await db.execute(sa_delete(Goal).where(Goal.user_id == user_id))
    await db.execute(sa_delete(Entry).where(Entry.user_id == user_id))
    await db.execute(sa_delete(Projection).where(Projection.user_id == user_id))
    await db.execute(sa_delete(Report).where(Report.user_id == user_id))
    await db.execute(sa_delete(DailySummary).where(DailySummary.user_id == user_id))
    await db.execute(sa_delete(PrivacySetting).where(PrivacySetting.user_id == user_id))
    await db.execute(sa_delete(AutoPlanLog).where(AutoPlanLog.user_id == user_id))
    await db.execute(sa_delete(UserKeys).where(UserKeys.user_id == user_id))
    # try FTS cleanup (best effort)
    try:
        await db.execute(text("DELETE FROM entries_fts WHERE rowid IN (SELECT id FROM entries WHERE user_id = :u)"), {"u": user_id})
    except Exception:
        pass


class SetAdminIn(BaseModel):
    is_admin: bool


@router.put("/users/{user_id}/admin")
async def set_admin(
    user_id: int,
    body: SetAdminIn,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Grant/revoke admin. Guards: cannot change yourself; cannot demote the last admin."""
    target = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if target.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能修改自己的管理员权限")
    if not body.is_admin and target.is_admin:
        admins = (
            await db.execute(select(User.id).where(User.is_admin == True))  # noqa: E712
        ).scalars().all()
        if len(admins) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能收回最后一个管理员")
    target.is_admin = body.is_admin
    await db.commit()
    return {"ok": True, "username": target.username, "is_admin": target.is_admin}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin can delete a user and all their data. Guards: cannot delete
    yourself; cannot delete the last admin."""
    target = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if target.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除当前登录的管理员自己")
    if target.is_admin:
        admins = (
            await db.execute(select(User.id).where(User.is_admin == True))  # noqa: E712
        ).scalars().all()
        if len(admins) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除最后一个管理员")
    await _delete_user_data(db, target.id)
    await db.delete(target)
    await db.commit()
    # P2-3: remove the user's attachment files from disk too
    import shutil

    from ..config import settings as cfg

    user_dir = Path(cfg.files_dir) / str(target.id)
    if user_dir.exists():
        shutil.rmtree(user_dir, ignore_errors=True)
    return {"ok": True, "deleted": target.username}

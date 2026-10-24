"""Pydantic request/response schemas."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["work", "routine", "diet", "study", "exercise", "social"]


# ---------- auth ----------

class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    token: str
    user_id: int
    username: str
    is_admin: bool


class PinSetupIn(BaseModel):
    pin: str = Field(min_length=6, max_length=32)


class PinVerifyIn(BaseModel):
    pin: str


class PinRecoverIn(BaseModel):
    username: str
    admin_password: str
    recovery_passphrase: str
    new_pin: str = Field(min_length=6, max_length=32)


class PinChangeIn(BaseModel):
    old_pin: str | None = None
    new_pin: str = Field(min_length=6, max_length=32)


# ---------- entries ----------

class EntryIn(BaseModel):
    categories: list[Category] = Field(min_length=1)
    title: str | None = None
    content: str | None = None
    mood: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None
    is_private: bool = False
    ai_allowed: bool = True
    extra_json: dict | None = None
    pin: str | None = None  # required to encrypt when is_private


class EntryUpdateIn(BaseModel):
    categories: list[Category] | None = None
    title: str | None = None
    content: str | None = None
    mood: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None
    ai_allowed: bool | None = None
    extra_json: dict | None = None
    pin: str | None = None


class EntryOut(BaseModel):
    id: int
    categories: list[str]
    primary_category: str
    title: str | None
    content: str | None
    mood: int | None
    tags: list[str] | None
    attachments: list[str] | None
    is_private: bool
    ai_allowed: bool
    extra_json: dict | None
    created_at: dt.datetime
    updated_at: dt.datetime


class PrivacyCategoryIn(BaseModel):
    category: Category
    visible: bool | None = None
    pin_required: bool | None = None
    ai_allowed: bool | None = None

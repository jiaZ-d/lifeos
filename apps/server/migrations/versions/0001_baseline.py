"""Baseline: all LifeOS v1.4 tables (matches app.db Base.metadata).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-23
"""
import sys
from pathlib import Path

from alembic import op

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db import Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.db import Base
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=op.get_bind())

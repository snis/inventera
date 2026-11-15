"""Initial clean v2.5 schema matching SQLAlchemy models.

Revision ID: 0001_initial_v25
Revises:
Create Date: 2026-11-15 14:18:30
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_v25"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=32), nullable=False, unique=True),
    )
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
    )
    op.create_table(
        "stores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
    )
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("value", sa.Text(), nullable=True),
    )
    op.create_table(
        "item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=32), nullable=False, unique=True),
        sa.Column("name_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id"), nullable=True),
        sa.Column("alert_quantity", sa.Integer(), nullable=True),
        sa.Column("last_checked", sa.DateTime(), nullable=True),
        sa.Column("location", sa.String(length=32), nullable=True),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column("store", sa.String(length=32), nullable=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("added_to_task", sa.DateTime(), nullable=True),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sqlite_autoincrement=True,
    )


def downgrade() -> None:
    op.drop_table("item")
    op.drop_table("settings")
    op.drop_table("stores")
    op.drop_table("locations")
    op.drop_table("units")

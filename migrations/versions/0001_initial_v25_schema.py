"""Initial v2.5 schema and legacy v1/v2.0 upgrade backfill.

Revision ID: 0001_initial_v25
Revises:
Create Date: 2026-11-15 13:28:30
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_v25"
down_revision = None
branch_labels = None
depends_on = None


def _ensure_option_table(inspector, table_name: str) -> None:
    if table_name not in inspector.get_table_names():
        op.create_table(
            table_name,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        )


def _backfill_options(bind) -> None:
    meta = sa.MetaData()
    meta.reflect(bind=bind, only=["item", "units", "locations", "stores", "settings"])

    item_tbl = meta.tables["item"]
    settings_tbl = meta.tables["settings"]
    option_tables = {
        "unit": meta.tables["units"],
        "location": meta.tables["locations"],
        "store": meta.tables["stores"],
    }

    def get_or_create(field: str, raw_name: str) -> tuple[int, str] | None:
        clean = (raw_name or "").strip()
        if not clean:
            return None
        tbl = option_tables[field]
        row = bind.execute(
            sa.select(tbl.c.id, tbl.c.name).where(sa.func.lower(tbl.c.name) == clean.lower())
        ).first()
        if row:
            return row.id, row.name
        res = bind.execute(tbl.insert().values(name=clean))
        return int(res.inserted_primary_key[0]), clean

    for field in ("unit", "location", "store"):
        row = bind.execute(
            sa.select(settings_tbl.c.value).where(settings_tbl.c.key == f"managed_options_{field}")
        ).first()
        if row and row.value:
            try:
                parsed = json.loads(row.value)
                if isinstance(parsed, list):
                    for val in parsed:
                        get_or_create(field, str(val))
            except (ValueError, TypeError):
                pass

    items = bind.execute(
        sa.select(
            item_tbl.c.id,
            item_tbl.c.unit,
            item_tbl.c.unit_id,
            item_tbl.c.location,
            item_tbl.c.location_id,
            item_tbl.c.store,
            item_tbl.c.store_id,
        )
    ).fetchall()

    for it in items:
        updates: dict = {}
        for field in ("unit", "location", "store"):
            fk_col = f"{field}_id"
            if getattr(it, fk_col) is None and (getattr(it, field) or "").strip():
                created = get_or_create(field, getattr(it, field))
                if created:
                    updates[fk_col] = created[0]
                    updates[field] = created[1]
        if updates:
            bind.execute(item_tbl.update().where(item_tbl.c.id == it.id).values(**updates))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    _ensure_option_table(inspector, "units")
    _ensure_option_table(inspector, "locations")
    _ensure_option_table(inspector, "stores")

    if "settings" not in existing_tables:
        op.create_table(
            "settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(length=64), nullable=False, unique=True),
            sa.Column("value", sa.Text(), nullable=True),
        )

    if "item" not in existing_tables:
        op.create_table(
            "item",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=64), nullable=False, unique=True),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("alert_quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(length=16), nullable=False),
            sa.Column("category", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("location", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("store", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id"), nullable=True),
            sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id"), nullable=True),
            sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=True),
            sa.Column("is_visible", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("last_checked", sa.DateTime(), nullable=True),
            sa.Column("task_id", sa.String(length=64), nullable=True),
            sa.Column("added_to_task", sa.DateTime(), nullable=True),
        )
    else:
        existing_cols = {col["name"] for col in inspector.get_columns("item")}
        if "unit_id" not in existing_cols:
            op.add_column("item", sa.Column("unit_id", sa.Integer(), nullable=True))
        if "location_id" not in existing_cols:
            op.add_column("item", sa.Column("location_id", sa.Integer(), nullable=True))
        if "store_id" not in existing_cols:
            op.add_column("item", sa.Column("store_id", sa.Integer(), nullable=True))
        if "is_visible" not in existing_cols:
            op.add_column(
                "item",
                sa.Column("is_visible", sa.Boolean(), nullable=False, server_default="1"),
            )
        if "task_id" not in existing_cols:
            op.add_column("item", sa.Column("task_id", sa.String(length=64), nullable=True))
        if "added_to_task" not in existing_cols:
            op.add_column("item", sa.Column("added_to_task", sa.DateTime(), nullable=True))
        if "last_checked" not in existing_cols:
            op.add_column("item", sa.Column("last_checked", sa.DateTime(), nullable=True))

    _backfill_options(bind)


def downgrade() -> None:
    op.drop_table("item")
    op.drop_table("settings")
    op.drop_table("stores")
    op.drop_table("locations")
    op.drop_table("units")

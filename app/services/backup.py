"""Backup export and atomic restore service for Inventera."""

from datetime import datetime
from typing import Any

from app.config import utc_now
from app.extensions import db
from app.models.item import Item, Location, Store, Unit
from app.models.settings import Settings
from app.services.options import get_or_create_option

BACKUP_SETTING_KEYS = ("ha_default_todo_entity", "ha_store_todo_map", "calendar_url")


def _parse_iso_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def export_backup_payload() -> dict[str, Any]:
    """Export all inventory items, options, and non-secret settings as a JSON-serializable dict."""
    items_data = []
    for item in Item.query.order_by(Item.id).all():
        items_data.append(
            {
                "name": item.name,
                "quantity": item.quantity,
                "alert_quantity": item.alert_quantity,
                "unit": item.unit,
                "location": item.location or "",
                "store": item.store or "",
                "is_visible": bool(item.is_visible),
                "last_checked": item.last_checked.isoformat() if item.last_checked else None,
                "added_to_task": item.added_to_task.isoformat() if item.added_to_task else None,
            }
        )

    settings_data = {
        key: Settings.get(key, "") for key in BACKUP_SETTING_KEYS if Settings.get(key) is not None
    }

    return {
        "version": "2.5",
        "exported_at": utc_now().isoformat(),
        "units": [u.name for u in Unit.query.order_by(Unit.name).all()],
        "locations": [loc.name for loc in Location.query.order_by(Location.name).all()],
        "stores": [s.name for s in Store.query.order_by(Store.name).all()],
        "items": items_data,
        "settings": settings_data,
    }


def restore_backup_payload(payload: dict[str, Any]) -> int:
    """
    Validate and restore a backup payload atomically (caller owns db.session.commit/rollback).
    Returns number of restored items.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("Invalid backup format: missing 'items' list")

    # Clear existing inventory and options cleanly (FK-safe order: Item first)
    Item.query.delete(synchronize_session=False)
    Unit.query.delete(synchronize_session=False)
    Location.query.delete(synchronize_session=False)
    Store.query.delete(synchronize_session=False)
    db.session.flush()

    for name in payload.get("units") or []:
        get_or_create_option("unit", str(name))
    for name in payload.get("locations") or []:
        get_or_create_option("location", str(name))
    for name in payload.get("stores") or []:
        get_or_create_option("store", str(name))

    restored_count = 0
    for raw_item in payload["items"]:
        if not isinstance(raw_item, dict):
            raise ValueError("Invalid item entry in backup")
        name = (raw_item.get("name") or "").strip()
        unit_name = (raw_item.get("unit") or "").strip()
        if not name or not unit_name:
            raise ValueError("Backup item missing required 'name' or 'unit'")

        qty = int(raw_item.get("quantity") or 0)
        alert_qty = int(raw_item.get("alert_quantity") or 0)
        if qty < 0 or alert_qty < 0:
            raise ValueError(f"Negative quantity for backup item '{name}'")

        unit_obj = get_or_create_option("unit", unit_name)
        loc_obj = get_or_create_option("location", str(raw_item.get("location") or ""))
        store_obj = get_or_create_option("store", str(raw_item.get("store") or ""))

        item = Item(
            name=name,
            quantity=qty,
            alert_quantity=alert_qty,
            unit=unit_obj.name,
            unit_id=unit_obj.id,
            category="",
            location=loc_obj.name if loc_obj else "",
            location_id=loc_obj.id if loc_obj else None,
            store=store_obj.name if store_obj else "",
            store_id=store_obj.id if store_obj else None,
            is_visible=bool(raw_item.get("is_visible", True)),
            last_checked=_parse_iso_dt(raw_item.get("last_checked")) or utc_now(),
            added_to_task=_parse_iso_dt(raw_item.get("added_to_task")),
        )
        db.session.add(item)
        restored_count += 1

    raw_settings = payload.get("settings") or {}
    if isinstance(raw_settings, dict):
        for key in BACKUP_SETTING_KEYS:
            if key in raw_settings and raw_settings[key] is not None:
                Settings.set(key, str(raw_settings[key]))

    db.session.flush()
    return restored_count

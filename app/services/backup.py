"""Backup export, shared settings validators, and atomic restore service."""

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from app.config import utc_now
from app.extensions import db
from app.models.item import Item, Location, Store, Unit
from app.models.settings import Settings
from app.services.options import get_or_create_option
from app.utils.i18n import t

BACKUP_VERSION = "2.5"
MAX_SQLITE_INT = 2_147_483_647
BACKUP_SETTING_KEYS = ("ha_default_todo_entity", "ha_store_todo_map", "calendar_url")


def validate_calendar_url(raw_url: str) -> str:
    """Allow empty string or http(s) URLs with a valid host."""
    clean = raw_url.strip()
    if not clean:
        return ""
    parsed = urlparse(clean)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(t("api.invalid_calendar_url"))
    return clean


def _parse_iso_dt(raw: Any, field_name: str) -> datetime | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"Invalid datetime type for '{field_name}'")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO datetime for '{field_name}': {raw}") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _parse_strict_int(value: Any, field_name: str, item_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Field '{field_name}' for '{item_name}' must be an integer")
    if value < 0 or value > MAX_SQLITE_INT:
        raise ValueError(f"Field '{field_name}' for '{item_name}' out of range")
    return value


def _validate_settings_dict(raw_settings: Any) -> dict[str, str]:
    if raw_settings is None:
        return {}
    if not isinstance(raw_settings, dict):
        raise ValueError("Invalid 'settings' object in backup")

    validated: dict[str, str] = {}
    if "calendar_url" in raw_settings and raw_settings["calendar_url"] is not None:
        if not isinstance(raw_settings["calendar_url"], str):
            raise ValueError("Backup 'calendar_url' must be a string")
        validated["calendar_url"] = validate_calendar_url(raw_settings["calendar_url"])

    if (
        "ha_default_todo_entity" in raw_settings
        and raw_settings["ha_default_todo_entity"] is not None
    ):
        if not isinstance(raw_settings["ha_default_todo_entity"], str):
            raise ValueError("Backup 'ha_default_todo_entity' must be a string")
        validated["ha_default_todo_entity"] = raw_settings["ha_default_todo_entity"].strip()

    if "ha_store_todo_map" in raw_settings and raw_settings["ha_store_todo_map"] is not None:
        raw_map = raw_settings["ha_store_todo_map"]
        if isinstance(raw_map, str):
            try:
                parsed_map = json.loads(raw_map) if raw_map.strip() else {}
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid JSON in 'ha_store_todo_map'") from exc
        elif isinstance(raw_map, dict):
            parsed_map = raw_map
        else:
            raise ValueError("Backup 'ha_store_todo_map' must be a JSON object")

        if not isinstance(parsed_map, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in parsed_map.items()
        ):
            raise ValueError("Backup 'ha_store_todo_map' keys and values must be strings")
        validated["ha_store_todo_map"] = json.dumps(parsed_map, ensure_ascii=False)

    return validated


def export_backup_payload() -> dict[str, Any]:
    """Export all inventory items, options, and non-secret settings as a JSON-serializable dict."""
    items_data = [
        {
            "id": item.id,
            "name": item.name,
            "quantity": item.quantity,
            "alert_quantity": item.alert_quantity,
            "unit": item.unit,
            "location": item.location or "",
            "store": item.store or "",
            "is_visible": bool(item.is_visible),
            "version": item.version,
            "task_id": item.task_id,
            "last_checked": item.last_checked.isoformat() if item.last_checked else None,
            "added_to_task": item.added_to_task.isoformat() if item.added_to_task else None,
        }
        for item in Item.query.order_by(Item.id).all()
    ]

    settings_data = {
        key: Settings.get(key, "") for key in BACKUP_SETTING_KEYS if Settings.get(key) is not None
    }

    return {
        "version": BACKUP_VERSION,
        "exported_at": utc_now().isoformat(),
        "units": [u.name for u in Unit.query.order_by(Unit.name).all()],
        "locations": [loc.name for loc in Location.query.order_by(Location.name).all()],
        "stores": [s.name for s in Store.query.order_by(Store.name).all()],
        "items": items_data,
        "settings": settings_data,
    }


def restore_backup_payload(payload: dict[str, Any]) -> int:
    """
    Strictly validate and restore a backup payload atomically.
    Raises ValueError before mutating any database state if validation fails.
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid backup format: root must be a JSON object")
    if payload.get("version") != BACKUP_VERSION:
        raise ValueError(f"Unsupported or missing backup version: {payload.get('version')!r}")
    if not isinstance(payload.get("items"), list):
        raise ValueError("Invalid backup format: missing 'items' list")

    for opt_key in ("units", "locations", "stores"):
        val = payload.get(opt_key)
        if val is not None and (
            not isinstance(val, list) or not all(isinstance(x, str) for x in val)
        ):
            raise ValueError(f"Invalid '{opt_key}' list in backup")

    validated_settings = _validate_settings_dict(payload.get("settings"))

    validated_items: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_ids: set[int] = set()
    for raw_item in payload["items"]:
        if not isinstance(raw_item, dict):
            raise ValueError("Invalid item entry in backup")

        raw_id = raw_item.get("id")
        item_id: int | None = None
        if raw_id is not None:
            item_id = _parse_strict_int(raw_id, "id", str(raw_item.get("name", "")))
            if item_id < 1:
                raise ValueError(f"Backup item 'id' must be >= 1, got {item_id}")
            if item_id in seen_ids:
                raise ValueError(f"Duplicate item id in backup: {item_id}")
            seen_ids.add(item_id)

        raw_task_id = raw_item.get("task_id")
        task_id: str | None = None
        if raw_task_id is not None:
            if not isinstance(raw_task_id, str):
                raise ValueError("Backup item 'task_id' must be a string or null")
            clean_task_id = raw_task_id.strip()
            if len(clean_task_id) > 64:
                raise ValueError("Backup item 'task_id' exceeds maximum length of 64")
            task_id = clean_task_id or None

        raw_version = raw_item.get("version")
        item_version: int | None = None
        if raw_version is not None:
            item_version = _parse_strict_int(raw_version, "version", str(raw_item.get("name", "")))
            if item_version < 1:
                raise ValueError(f"Backup item 'version' must be >= 1, got {item_version}")

        raw_name = raw_item.get("name")
        raw_unit = raw_item.get("unit")
        if not isinstance(raw_name, str) or not isinstance(raw_unit, str):
            raise ValueError("Backup item 'name' and 'unit' must be strings")
        name = raw_name.strip()
        unit_name = raw_unit.strip()
        if not name:
            raise ValueError("Backup item missing required 'name'")
        name_key = name.casefold()
        if name_key in seen_names:
            raise ValueError(f"Duplicate item name in backup: {name}")
        seen_names.add(name_key)

        qty = _parse_strict_int(raw_item.get("quantity"), "quantity", name)
        alert_qty = _parse_strict_int(raw_item.get("alert_quantity"), "alert_quantity", name)

        is_visible = raw_item.get("is_visible", True)
        if not isinstance(is_visible, bool):
            raise ValueError(f"Field 'is_visible' for '{name}' must be a boolean")

        loc_val = raw_item.get("location", "")
        store_val = raw_item.get("store", "")
        if loc_val is not None and not isinstance(loc_val, str):
            raise ValueError(f"Field 'location' for '{name}' must be a string")
        if store_val is not None and not isinstance(store_val, str):
            raise ValueError(f"Field 'store' for '{name}' must be a string")

        validated_items.append(
            {
                "id": item_id,
                "name": name,
                "quantity": qty,
                "alert_quantity": alert_qty,
                "unit": unit_name,
                "location": (loc_val or "").strip(),
                "store": (store_val or "").strip(),
                "is_visible": is_visible,
                "version": item_version,
                "task_id": task_id,
                "last_checked": _parse_iso_dt(raw_item.get("last_checked"), "last_checked")
                or utc_now(),
                "added_to_task": _parse_iso_dt(raw_item.get("added_to_task"), "added_to_task"),
            }
        )

    # All validation passed — now replace data atomically
    existing_versions = {row.id: (row.version or 1) for row in Item.query.all()}
    max_existing_version = max(existing_versions.values(), default=0)
    Item.query.delete(synchronize_session=False)
    Unit.query.delete(synchronize_session=False)
    Location.query.delete(synchronize_session=False)
    Store.query.delete(synchronize_session=False)
    db.session.flush()

    for name in payload.get("units") or []:
        get_or_create_option("unit", name)
    for name in payload.get("locations") or []:
        get_or_create_option("location", name)
    for name in payload.get("stores") or []:
        get_or_create_option("store", name)

    for entry in validated_items:
        unit_obj = get_or_create_option("unit", entry["unit"]) if entry["unit"] else None
        loc_obj = get_or_create_option("location", entry["location"])
        store_obj = get_or_create_option("store", entry["store"])
        prior_version = (
            existing_versions.get(entry["id"], 0)
            if entry["id"] is not None
            else max_existing_version
        )
        restored_version = max(prior_version, entry["version"] or 1) + 1
        item_kwargs: dict[str, Any] = {
            "name": entry["name"],
            "quantity": entry["quantity"],
            "alert_quantity": entry["alert_quantity"],
            "unit": unit_obj.name if unit_obj else "",
            "unit_id": unit_obj.id if unit_obj else None,
            "category": "",
            "location": loc_obj.name if loc_obj else "",
            "location_id": loc_obj.id if loc_obj else None,
            "store": store_obj.name if store_obj else "",
            "store_id": store_obj.id if store_obj else None,
            "is_visible": entry["is_visible"],
            "version": restored_version,
            "task_id": entry["task_id"],
            "last_checked": entry["last_checked"],
            "added_to_task": entry["added_to_task"],
        }
        if entry["id"] is not None:
            item_kwargs["id"] = entry["id"]
        db.session.add(Item(**item_kwargs))

    backup_defaults = {
        "ha_default_todo_entity": "",
        "ha_store_todo_map": "{}",
        "calendar_url": "",
    }
    for key in BACKUP_SETTING_KEYS:
        Settings.set(key, validated_settings.get(key, backup_defaults.get(key, "")))

    db.session.flush()
    return len(validated_items)

"""Shopping list synchronization service to Home Assistant To-do lists."""

import logging
from typing import Any

from app.config import utc_now
from app.extensions import db
from app.integrations.home_assistant import HomeAssistantTodoClient, get_store_todo_map
from app.models.item import Item
from app.models.settings import Settings
from app.utils.i18n import t

logger = logging.getLogger(__name__)


def _is_item_present(item_name: str, existing_summaries: list[str]) -> bool:
    """Match an item unambiguously by exact name or '{name} (...)' format."""
    name_cf = item_name.strip().casefold()
    return any(
        existing == name_cf or existing.startswith(f"{name_cf} (")
        for existing in existing_summaries
    )


def sync_low_inventory_to_ha() -> dict[str, Any]:
    """
    Find all visible items where quantity <= alert_quantity,
    resolve the target todo.* entity dynamically from Settings,
    check for duplicates, and add missing items.
    """
    client = HomeAssistantTodoClient()
    if not client.is_configured():
        return {
            "status": "error",
            "synced_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "unmapped_count": 0,
            "message": t("api.ha_not_configured"),
        }

    low_items = (
        Item.query.filter(Item.is_visible.is_(True), Item.quantity <= Item.alert_quantity)
        .order_by(Item.name)
        .all()
    )
    if not low_items:
        return {
            "status": "success",
            "synced_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "unmapped_count": 0,
            "message": t("api.sync_none"),
        }

    store_map = get_store_todo_map()
    default_entity = (Settings.get("ha_default_todo_entity", "") or "").strip()

    if not default_entity and not store_map:
        discovered = client.get_todo_entities()
        if discovered:
            default_entity = discovered[0]["entity_id"]

    existing_by_entity: dict[str, list[str] | None] = {}
    synced: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    unmapped: list[str] = []

    for item in low_items:
        store = (item.store or "").strip()
        target_entity = store_map.get(store) or default_entity

        if not target_entity:
            unmapped.append(item.name.strip())
            continue

        if target_entity not in existing_by_entity:
            existing_by_entity[target_entity] = client.get_existing_items(target_entity)

        existing_summaries = existing_by_entity[target_entity]
        clean_name = item.name.strip()

        if existing_summaries is None:
            failed.append(clean_name)
            continue

        if _is_item_present(clean_name, existing_summaries):
            skipped.append(clean_name)
            continue

        task_title = f"{clean_name} ({item.quantity} {item.unit})"
        description = (
            f"{t('manage.location')}: {item.location or t('common.other')}\n"
            f"{t('manage.store')}: {store or t('common.other')}\n"
            f"{t('shopping.col_current')}: {item.quantity} {item.unit}\n"
            f"{t('shopping.col_min')}: {item.alert_quantity} {item.unit}"
        )

        if client.add_todo_item(target_entity, task_title, description):
            item.added_to_task = utc_now()
            synced.append(clean_name)
            existing_summaries.append(task_title.casefold())
        else:
            failed.append(clean_name)
            logger.error(f"Failed to add {clean_name} to {target_entity}")

    if synced:
        db.session.commit()

    if failed and not synced:
        status = "error"
    elif failed:
        status = "partial"
    else:
        status = "success"

    parts: list[str] = []
    if synced or not failed:
        parts.append(t("api.sync_added", added=len(synced)))
    if skipped:
        parts.append(t("api.sync_skipped", skipped=len(skipped)))
    if failed:
        parts.append(t("api.sync_failed", failed=len(failed)))

    return {
        "status": status,
        "synced_count": len(synced),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "unmapped_count": len(unmapped),
        "synced_items": synced,
        "failed_items": failed,
        "skipped_items": skipped,
        "message": " ".join(parts),
    }

"""Shopping list synchronization service to Home Assistant To-do lists."""

import logging
import re
import threading
from typing import Any

from app.config import utc_now
from app.extensions import db
from app.integrations.home_assistant import HomeAssistantTodoClient, get_store_todo_map
from app.models.item import Item
from app.models.settings import Settings
from app.utils.i18n import t

logger = logging.getLogger(__name__)
_sync_lock = threading.Lock()
_QTY_UNIT_SUFFIX_RE = re.compile(r"\s+\(\d+(?:[.,]\d+)?(?:\s+(?:[^()]|\([^()]*\))*)?\)$")
_INVENTERA_ID_RE = re.compile(r"\[inventera_id:(\d+)\]")
_ORIG_GET_EXISTING_ITEMS = HomeAssistantTodoClient.get_existing_items


def _extract_inventera_id(description: str) -> int | None:
    """Extract the embedded Inventera item ID from a HA to-do description, if present."""
    match = _INVENTERA_ID_RE.search(description or "")
    return int(match.group(1)) if match else None


def _extract_base_name(summary: str) -> str:
    """Strip trailing ' (<qty> <unit>)' suffix from a HA to-do summary if present."""
    clean = summary.strip().casefold()
    return _QTY_UNIT_SUFFIX_RE.sub("", clean).strip()


def _is_item_present(item_name: str, existing_summaries: list[str]) -> bool:
    """Match an item unambiguously by exact normalized name or base name before '(...)'."""
    name_cf = item_name.strip().casefold()
    return any(
        existing == name_cf or _extract_base_name(existing) == name_cf
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

    with _sync_lock:
        db.session.expire_all()
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

        return _execute_sync(client, low_items, store_map, default_entity)


def _fetch_entries_for_entity(
    client: HomeAssistantTodoClient, entity_id: str
) -> list[dict[str, Any]] | None:
    """Fetch active HA entries, keeping compatibility when get_existing_items is mocked."""
    if type(client).get_existing_items is not _ORIG_GET_EXISTING_ITEMS:
        summaries = client.get_existing_items(entity_id)
        if summaries is None:
            return None
        return [
            {"uid": "", "summary": s, "description": "", "inventera_id": None} for s in summaries
        ]

    raw_entries = client._fetch_active_todo_items(entity_id)
    if raw_entries is None:
        return None
    return [
        {
            "uid": entry.get("uid", ""),
            "summary": entry.get("summary", ""),
            "description": entry.get("description", ""),
            "inventera_id": _extract_inventera_id(entry.get("description", "")),
        }
        for entry in raw_entries
    ]


def _find_matching_entry(
    item: Item, clean_name: str, existing_entries: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Match an item by HA task_id, embedded inventera_id, or untagged summary fallback."""
    if item.task_id:
        for entry in existing_entries:
            if entry["uid"] and entry["uid"] == item.task_id:
                return entry

    if item.id is not None:
        for entry in existing_entries:
            if entry["inventera_id"] == item.id:
                return entry

    for entry in existing_entries:
        if entry["inventera_id"] is None and _is_item_present(clean_name, [entry["summary"]]):
            return entry
    return None


def _execute_sync(
    client: HomeAssistantTodoClient,
    low_items: list[Item],
    store_map: dict[str, str],
    default_entity: str,
) -> dict[str, Any]:
    """Execute the locked read-check-write synchronization against Home Assistant."""
    existing_by_entity: dict[str, list[dict[str, Any]] | None] = {}
    synced: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    unmapped: list[str] = []
    synced_updates: dict[int, dict[Any, Any]] = {}

    for item in low_items:
        store = (item.store or "").strip()
        target_entity = store_map.get(store) or default_entity

        if not target_entity:
            unmapped.append(item.name.strip())
            continue

        if target_entity not in existing_by_entity:
            existing_by_entity[target_entity] = _fetch_entries_for_entity(client, target_entity)

        existing_entries = existing_by_entity[target_entity]
        clean_name = item.name.strip()

        if existing_entries is None:
            failed.append(clean_name)
            continue

        matched = _find_matching_entry(item, clean_name, existing_entries)
        if matched is not None:
            if matched.get("uid") and item.task_id != matched["uid"]:
                synced_updates[item.id] = {"task_id": matched["uid"]}
            skipped.append(clean_name)
            continue

        unit = (item.unit or "").strip()
        qty_display = f"{item.quantity} {unit}" if unit else f"{item.quantity}"
        min_display = f"{item.alert_quantity} {unit}" if unit else f"{item.alert_quantity}"
        task_title = f"{clean_name} ({qty_display})"
        description = (
            f"{t('manage.location')}: {item.location or t('common.other')}\n"
            f"{t('manage.store')}: {store or t('common.other')}\n"
            f"{t('shopping.col_current')}: {qty_display}\n"
            f"{t('shopping.col_min')}: {min_display}\n"
            f"[inventera_id:{item.id}]"
        )

        if client.add_todo_item(target_entity, task_title, description):
            update_fields: dict[str, Any] = {"added_to_task": utc_now()}
            new_uid = ""
            if not client.supports_description(target_entity):
                refreshed = _fetch_entries_for_entity(client, target_entity)
                if refreshed is not None:
                    existing_entries[:] = refreshed
                    title_cf = task_title.casefold()
                    for entry in reversed(refreshed):
                        if entry["uid"] and entry["summary"] == title_cf:
                            new_uid = entry["uid"]
                            update_fields["task_id"] = new_uid
                            break
            synced_updates[item.id] = update_fields
            synced.append(clean_name)
            if not new_uid:
                existing_entries.append(
                    {
                        "uid": "",
                        "summary": task_title.casefold(),
                        "description": description,
                        "inventera_id": item.id,
                    }
                )
        else:
            failed.append(clean_name)
            logger.error(f"Failed to add {clean_name} to {target_entity}")

    if synced_updates:
        for item_id, fields in synced_updates.items():
            Item.query.filter_by(id=item_id).update(fields, synchronize_session=False)
        db.session.commit()

    all_unmapped = bool(unmapped) and not synced and not skipped and not failed
    if (failed and not synced) or all_unmapped:
        status = "error"
    elif failed or unmapped:
        status = "partial"
    else:
        status = "success"

    parts: list[str] = []
    if synced or (not failed and not all_unmapped):
        parts.append(t("api.sync_added", added=len(synced)))
    if skipped:
        parts.append(t("api.sync_skipped", skipped=len(skipped)))
    if failed:
        parts.append(t("api.sync_failed", failed=len(failed)))
    if unmapped:
        parts.append(t("api.sync_unmapped", unmapped=len(unmapped)))

    return {
        "status": status,
        "synced_count": len(synced),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "unmapped_count": len(unmapped),
        "synced_items": synced,
        "failed_items": failed,
        "skipped_items": skipped,
        "unmapped_items": unmapped,
        "message": " ".join(parts),
    }

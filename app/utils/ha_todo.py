"""
Home Assistant To-do integration for Inventera.
Supports dynamic discovery of all Home Assistant todo.* entities
(Local To-do, Google Tasks, Todoist, Bring!, etc.) and dynamic store mapping.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any

import requests

from app import db
from app.models.item import Item
from app.models.settings import Settings
from app.utils.i18n import t

logger = logging.getLogger(__name__)


def get_ha_config() -> tuple[str, str, bool]:
    """
    Resolve Home Assistant API URL and token.
    Prioritizes Supervisor Add-on environment (SUPERVISOR_TOKEN),
    then database Settings, then environment variables (HA_URL, HA_TOKEN).

    Returns:
        Tuple of (base_url, token, is_supervisor_addon)
    """
    supervisor_token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if supervisor_token:
        return "http://supervisor/core", supervisor_token, True

    db_url = (Settings.get("ha_url", "") or "").strip()
    db_token = (Settings.get("ha_token", "") or "").strip()

    base_url = db_url or os.environ.get("HA_URL", "").strip()
    token = db_token or os.environ.get("HA_TOKEN", "").strip()
    return base_url.rstrip("/"), token, False


def get_store_todo_map() -> dict[str, str]:
    """Load store -> todo.* entity_id mapping from Settings."""
    raw = Settings.get("ha_store_todo_map", "{}")
    try:
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_store_todo_map(mapping: dict[str, str]) -> None:
    """Persist store -> todo.* entity_id mapping in Settings."""
    clean = {k.strip(): v.strip() for k, v in mapping.items() if k.strip() and v.strip()}
    Settings.set("ha_store_todo_map", json.dumps(clean, ensure_ascii=False))


class HomeAssistantTodoClient:
    """Client for interacting with Home Assistant To-do API"""

    def __init__(self, base_url: str | None = None, token: str | None = None):
        cfg_url, cfg_token, is_addon = get_ha_config()
        self.base_url = (base_url if base_url is not None else cfg_url).rstrip("/")
        self.token = token if token is not None else cfg_token
        self.is_addon = is_addon
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def is_configured(self) -> bool:
        return bool(self.base_url and self.token)

    def test_connection(self) -> tuple[bool, str]:
        """Verify connectivity and authentication with Home Assistant API."""
        if not self.is_configured():
            return False, t("api.ha_not_configured")
        try:
            resp = requests.get(f"{self.base_url}/api/", headers=self.headers, timeout=5)
            if resp.status_code == 200:
                return True, t("settings.connection_ok")
            return False, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)

    def get_todo_entities(self) -> list[dict[str, str]]:
        """
        Discover all todo.* entities in Home Assistant regardless of integration
        (Local To-do, Google Tasks, Todoist, etc.).
        """
        if not self.is_configured():
            return []
        try:
            resp = requests.get(f"{self.base_url}/api/states", headers=self.headers, timeout=8)
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch HA states: HTTP {resp.status_code}")
                return []
            entities = []
            for state in resp.json():
                entity_id = state.get("entity_id", "")
                if entity_id.startswith("todo."):
                    friendly = state.get("attributes", {}).get("friendly_name") or entity_id
                    entities.append({"entity_id": entity_id, "name": friendly})
            return sorted(entities, key=lambda e: e["name"].lower())
        except Exception as e:
            logger.error(f"Error discovering todo entities: {str(e)}")
            return []

    def get_existing_items(self, entity_id: str) -> list[str]:
        """
        Get existing active items from a HA to-do list.
        Returns list of lowercase item summaries to prevent duplicates.
        """
        try:
            url = f"{self.base_url}/api/services/todo/get_items?return_response"
            resp = requests.post(
                url, headers=self.headers, json={"entity_id": entity_id}, timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("service_response", {}).get(entity_id, {}).get("items", [])
                active_summaries = [
                    item.get("summary", "").strip().lower()
                    for item in items
                    if item.get("status") == "needs_action"
                ]
                return active_summaries
        except Exception as e:
            logger.warning(f"Could not retrieve existing tasks from {entity_id}: {str(e)}")
        return []

    def add_todo_item(self, entity_id: str, summary: str, description: str | None = None) -> bool:
        """Add an item to a Home Assistant to-do list."""
        try:
            url = f"{self.base_url}/api/services/todo/add_item"
            payload: dict[str, Any] = {"entity_id": entity_id, "item": summary}
            if description:
                payload["description"] = description
            resp = requests.post(url, headers=self.headers, json=payload, timeout=5)
            return resp.status_code in (200, 201)
        except Exception as e:
            logger.error(f"Failed to add todo item to {entity_id}: {str(e)}")
            return False


def sync_low_inventory_to_ha() -> dict[str, Any]:
    """
    Find all items where quantity <= alert_quantity,
    resolve the target todo.* entity dynamically from Settings,
    check for duplicates, and add missing items.
    """
    client = HomeAssistantTodoClient()
    if not client.is_configured():
        return {"status": "error", "synced_count": 0, "message": t("api.ha_not_configured")}

    low_items = (
        Item.query.filter(Item.is_visible.is_(True), Item.quantity <= Item.alert_quantity)
        .order_by(Item.name)
        .all()
    )
    if not low_items:
        return {"status": "success", "synced_count": 0, "message": t("api.sync_none")}

    store_map = get_store_todo_map()
    default_entity = (Settings.get("ha_default_todo_entity", "") or "").strip()

    # Fallback: if no default is set, try first discovered todo.* entity
    if not default_entity and not store_map:
        discovered = client.get_todo_entities()
        if discovered:
            default_entity = discovered[0]["entity_id"]

    existing_by_entity: dict[str, list[str]] = {}
    synced = []
    skipped = []
    unmapped = []

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

        already_present = any(
            clean_name.lower() in existing or existing.startswith(clean_name.lower())
            for existing in existing_summaries
        )

        if already_present:
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
            item.added_to_task = datetime.now()
            synced.append(clean_name)
            existing_summaries.append(task_title.lower())
        else:
            logger.error(f"Failed to add {clean_name} to {target_entity}")

    db.session.commit()

    parts = [t("api.sync_added", added=len(synced))]
    if skipped:
        parts.append(t("api.sync_skipped", skipped=len(skipped)))

    return {
        "status": "success",
        "synced_count": len(synced),
        "skipped_count": len(skipped),
        "unmapped_count": len(unmapped),
        "synced_items": synced,
        "skipped_items": skipped,
        "message": " ".join(parts),
    }

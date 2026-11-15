"""Home Assistant REST API integration for todo.* entities."""

import json
import logging
import os
from typing import Any

import requests

from app.models.settings import Settings
from app.utils.i18n import t

logger = logging.getLogger(__name__)


def get_ha_config() -> tuple[str, str, bool]:
    """
    Resolve Home Assistant API URL and token.
    Prioritizes Supervisor Add-on environment (SUPERVISOR_TOKEN),
    then database Settings, then environment variables (HA_URL, HA_TOKEN).
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
    """Stage store -> todo.* entity_id mapping in Settings."""
    clean = {k.strip(): v.strip() for k, v in mapping.items() if k.strip() and v.strip()}
    Settings.set("ha_store_todo_map", json.dumps(clean, ensure_ascii=False))


class HomeAssistantTodoClient:
    """Client for interacting with Home Assistant To-do API."""

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
        """Discover all todo.* entities in Home Assistant."""
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

    def get_existing_items(self, entity_id: str) -> list[str] | None:
        """
        Get existing active items from a HA to-do list.
        Returns normalized item summaries, or None if the list could not be read.
        """
        try:
            url = f"{self.base_url}/api/services/todo/get_items?return_response"
            resp = requests.post(
                url, headers=self.headers, json={"entity_id": entity_id}, timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("service_response", {}).get(entity_id, {}).get("items", [])
                return [
                    item.get("summary", "").strip().casefold()
                    for item in items
                    if item.get("status") == "needs_action"
                ]
            logger.warning(
                f"Failed to retrieve existing tasks from {entity_id}: HTTP {resp.status_code}"
            )
        except Exception as e:
            logger.warning(f"Could not retrieve existing tasks from {entity_id}: {str(e)}")
        return None

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

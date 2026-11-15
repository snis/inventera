# CLAUDE.md

Guidance for AI assistants working in the Inventera repository.

## Build & Run Commands
- Run locally: `python run.py`
- Syntax check: `python3 -m py_compile app/__init__.py app/models/item.py app/models/settings.py app/controllers/main.py app/controllers/inventory.py app/controllers/settings.py app/utils/helpers.py app/utils/ha_todo.py app/utils/i18n.py`
- Translation JSON check: `python3 -m json.tool app/translations/sv.json >/dev/null && python3 -m json.tool app/translations/en.json >/dev/null`
- Docker build: `docker build -t inventera .`
- Production deploy (`pod01`): `cd /opt/docker/homemade && docker compose build --no-cache inventory-app && docker compose up -d inventory-app`

## Architecture
- **App factory**: `app/__init__.py` (`create_app`), configured with `ProxyFix` for reverse proxies and Home Assistant Ingress.
- **Models**:
  - `app/models/item.py`: `Item`, `Unit`, `Location`, `Store` (SQLite via Flask-SQLAlchemy). `Item` links to `Unit`/`Location`/`Store` via `unit_id`/`location_id`/`store_id` while keeping string columns synced. `is_visible` controls visibility on `/` and `/shopping`.
  - `app/models/settings.py`: `Settings` key-value table (stores `ha_url`, `ha_token`, `ha_default_todo_entity`, `ha_store_todo_map`, `calendar_url`).
- **Controllers (Blueprints)**:
  - `app/controllers/main.py`: `/` inventory check grouped by location.
  - `app/controllers/inventory.py`: `/inventory` (sortable by `name`, `location`, `store`; default `location`), `/update_items`, `/toggle_visibility/<item_id>`, `/remove_item/<item_id>`, `/shopping`, `/sync_shopping_list`.
  - `app/controllers/settings.py`: `/settings`, `/settings/save`, `/settings/test_ha`, `/set_language/<lang>`.
- **i18n**: `app/utils/i18n.py` with `app/translations/sv.json` and `app/translations/en.json`. All user-facing strings must be added to both translation files.
- **Schema migration**: `ensure_option_schema_and_backfill()` in `app/utils/helpers.py` runs on startup to add new columns and backfill `Unit`/`Location`/`Store` IDs safely without manual migration scripts.

## Code Style Guidelines
- Follow PEP 8 (4-space indentation, `snake_case` functions/variables, `CamelCase` classes).
- Write code, docstrings, and comments in English; keep UI translations in `sv.json` and `en.json`.
- Always commit `db.session` changes before returning JSON from AJAX endpoints.
- Never commit `instance/db.sqlite3`, `.env`, or tokens/credentials to git.

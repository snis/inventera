# CLAUDE.md

Guidance for AI assistants working in the Inventera repository.

## Build & Run Commands
- Install/sync dependencies: `uv sync`
- Initialize/upgrade local DB: `uv run flask --app wsgi db upgrade`
- Run locally: `uv run run.py`
- Run tests: `uv run pytest -v`
- Lint & format check: `uv run ruff check . && uv run ruff format --check .`
- Security scan: `uv run semgrep scan --config p/python --config p/flask --metrics=off app/`
- Translation JSON check: `python3 -m json.tool app/translations/sv.json >/dev/null && python3 -m json.tool app/translations/en.json >/dev/null`
- Docker build: `docker build -t inventera .`
- Production deploy (`pod01`): `cd /opt/docker/homemade && docker compose build --no-cache inventory-app && docker compose up -d inventory-app`

## Architecture
- **App factory & config**: `app/__init__.py` (`create_app`), `app/config.py` (UTC time helper `utc_now()`, add-on `/data` vs local `instance/` storage, persistent `.secret_key`), `app/extensions.py` (`db`, `migrate`, `csrf`). `IngressMiddleware` handles `X-Ingress-Path` and restricts add-on traffic to the trusted Ingress proxy.
- **Production entrypoint**: `wsgi.py` (`gunicorn` runs `wsgi:app` after `flask --app wsgi db upgrade`).
- **Models**:
  - `app/models/item.py`: `Item`, `Unit`, `Location`, `Store` (SQLite via Flask-SQLAlchemy). `Item` links to `Unit`/`Location`/`Store` via `unit_id`/`location_id`/`store_id` while keeping string columns synced. `is_visible` controls visibility on `/` and `/shopping`.
  - `app/models/settings.py`: `Settings` key-value table (caller owns transaction/commit).
- **Services, Integrations & Presentation**:
  - `app/services/inventory.py`: grouped inventory and low-stock queries.
  - `app/services/options.py`: `Unit`/`Location`/`Store` CRUD and item syncing.
  - `app/services/shopping_sync.py`: Home Assistant To-do synchronization with unambiguous duplicate detection.
  - `app/integrations/home_assistant.py`: Home Assistant REST API client and config resolution.
  - `app/presentation/colors.py`: row age and stock-level color calculation.
- **Controllers (Blueprints)**:
  - `app/controllers/main.py`: `/` inventory check grouped by location.
  - `app/controllers/inventory.py`: `/inventory` (sortable by `name`, `location`, `store`; default `location`), `/update_items`, `/toggle_visibility/<item_id>`, `/remove_item/<item_id>`, `/shopping`, `/sync_ha`.
  - `app/controllers/settings.py`: `/settings`, `/settings/save` (atomic transaction), `/settings/test_ha`, `/set_language/<lang>`.
- **Templates & Static**: `app/templates/base.html` shared layout with CSRF meta tag and local vendor assets (`app/static/vendor/` — no external CDNs).
- **Migrations**: Alembic / Flask-Migrate in `migrations/`. The initial schema targets fresh installations; pre-release schema changes do not require legacy upgrades. Never replace an existing development database automatically.
- **i18n**: `app/utils/i18n.py` with `app/translations/sv.json` and `app/translations/en.json`.

## Code Style Guidelines
- Follow PEP 8 (4-space indentation, `snake_case` functions/variables, `CamelCase` classes).
- Write code, docstrings, and comments in English; keep UI translations in `sv.json` and `en.json`.
- Always commit `db.session` changes in the controller/operation boundary (never inside models) and rollback on error.
- Never commit `instance/db.sqlite3`, `.env`, or tokens/credentials to git.

# Inventera (v2.5)

Inventera is a modern, mobile-friendly inventory and shopping list web application built with Flask and SQLite, designed to integrate seamlessly with **Home Assistant** (via Ingress, iframe, or standalone) and **Home Assistant To-do lists**.

## Features

- **Inventory Check (`/`)**:
  - Grouped by **Location** with collapsible sections (collapsed state remembered in `localStorage`).
  - Large touch-friendly `+` / `−` stepper controls and instant `✓` save via AJAX.
  - Color-coded status gradients: left side reflects stock level (`quantity` vs `alert_quantity`), right side reflects days since last checked.
- **Shopping List & Home Assistant To-do Sync (`/shopping`)**:
  - Automatically lists visible items at or below their minimum threshold (`quantity <= alert_quantity`), grouped by **Store**.
  - One-click sync to **Home Assistant `todo.*` entities** (Local To-do, Google Tasks, Todoist, etc.) using configurable store-to-list mappings.
- **Manage Items (`/inventory`)**:
  - Wide responsive table with a **sticky header** on scroll.
  - **Sortable columns** by **Name**, **Location** (default), and **Store** with pagination support.
  - **Dropdowns** for **Unit**, **Location**, and **Store** backed by database IDs (`units`, `locations`, `stores` tables).
  - **Visibility toggle** (eye icon) to hide/pause discontinued or seasonal items from the Inventory check and Shopping list without deleting them.
  - Rename items in place without creating duplicates.
- **Settings (`/settings`)**:
  - Configure **Home Assistant** URL and Long-Lived Access Token (or automatic Supervisor API when running as an HA Add-on), with connection test and live `todo.*` discovery.
  - Map each **Store** (plus a fallback default) to a Home Assistant `todo.*` list.
  - **Add, rename (updates all linked items by ID), and delete** Units, Locations, and Stores.
  - Optional external Calendar / Overview link in the navigation bar.
- **i18n & Home Assistant Theme**:
  - Full **Swedish (`sv`)** and **English (`en`)** support via JSON translation files (`app/translations/`), switchable in the navbar.
  - Automatic Home Assistant theme & dark mode bridge (`app/static/ha-theme.js`).

## Installation & Deployment

### Docker Compose (Recommended)

```yaml
services:
  inventory-app:
    build: https://github.com/snis/inventera.git#v2.5
    container_name: inventory-app
    environment:
      - TZ=Europe/Stockholm
    volumes:
      - /path/to/inventory-db:/app/instance
    restart: unless-stopped
```

### Local Development

1. Clone the repository and sync dependencies with [uv](https://docs.astral.sh/uv/):
   ```bash
   git clone https://github.com/snis/inventera.git
   cd inventera
   uv sync
   ```
2. Run the application:
   ```bash
   uv run run.py
   ```
3. Open `http://localhost:5000` in your browser.

On startup, `db.create_all()` and `ensure_option_schema_and_backfill()` automatically create tables, migrate missing columns (`unit_id`, `location_id`, `store_id`, `is_visible`), and backfill ID-backed options from existing items.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `TZ` | Container timezone | System default |
| `SECRET_KEY` | Flask session secret key | Random per-start |
| `HA_URL` | Optional initial Home Assistant URL (overridden by Settings DB) | `""` |
| `HA_TOKEN` | Optional initial Home Assistant token (overridden by Settings DB) | `""` |
| `CALENDAR_URL` | Optional initial calendar link (overridden by Settings DB) | `""` |

## Project Structure

```text
inventera/
├── app/
│   ├── __init__.py             # App factory, ProxyFix, i18n globals, DB init & backfill
│   ├── controllers/
│   │   ├── main.py             # Main inventory check view (/)
│   │   ├── inventory.py        # Manage items (/inventory), AJAX update/add/delete/visibility, /shopping
│   │   └── settings.py         # Settings (/settings), HA test, language switcher
│   ├── models/
│   │   ├── item.py             # Item, Unit, Location, Store SQLAlchemy models
│   │   └── settings.py         # Settings key-value store
│   ├── static/
│   │   ├── style.css           # Responsive light/dark styling & HA theme variables
│   │   └── ha-theme.js         # Parent HA iframe theme & dark mode bridge
│   ├── templates/
│   │   ├── includes/           # Navbar & pagination partials
│   │   ├── index.html          # Inventory check view
│   │   ├── inventory.html      # Manage items view
│   │   ├── shopping.html       # Shopping list & HA Todo sync view
│   │   ├── settings.html       # Admin settings view
│   │   └── error.html          # Error page
│   ├── translations/
│   │   ├── sv.json             # Swedish translations
│   │   └── en.json             # English translations
│   └── utils/
│       ├── ha_todo.py          # Home Assistant REST API client & todo.* sync
│       ├── helpers.py          # Color helpers, grouping, schema backfill & option CRUD
│       ├── i18n.py             # JSON translation loader & locale detection
│       └── responses.py        # AJAX/HTML response helpers
├── instance/                   # SQLite database directory (gitignored)
├── pyproject.toml              # Project metadata & dependencies (uv)
├── uv.lock                     # Locked dependency versions
├── run.py                      # Application entry point
└── Dockerfile
```

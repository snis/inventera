"""
Settings blueprint for the inventory application.
Handles Home Assistant connection configuration, dynamic store-to-todo mapping,
language selection, and general app settings.
"""

import json
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.config import utc_now
from app.extensions import db
from app.integrations.home_assistant import (
    HomeAssistantTodoClient,
    get_ha_config,
    get_store_todo_map,
    save_store_todo_map,
)
from app.models.settings import Settings
from app.services.backup import export_backup_payload, restore_backup_payload, validate_calendar_url
from app.services.options import (
    OPTION_FIELDS,
    get_distinct_field_values,
    get_managed_options,
    save_managed_options_crud,
)
from app.utils.i18n import SUPPORTED_LANGUAGES, t

settings_bp = Blueprint("settings", __name__)


def _safe_referrer_url() -> str:
    """Return request.referrer only if it points to the same host or a local path."""
    fallback = url_for("main.index")
    ref = (request.referrer or "").strip()
    if not ref:
        return fallback
    parsed = urlsplit(ref)
    if not parsed.scheme and not parsed.netloc:
        if parsed.path.startswith("/") and not parsed.path.startswith("//"):
            return ref
        return fallback
    if parsed.scheme in ("http", "https") and parsed.netloc == request.host:
        return ref
    return fallback


@settings_bp.route("/set_language/<lang>")
def set_language(lang: str):
    """Switch active UI language and persist in session and cookie."""
    clean_lang = lang[:2].lower()
    if clean_lang not in SUPPORTED_LANGUAGES:
        clean_lang = "en"
    session["lang"] = clean_lang
    resp = make_response(redirect(_safe_referrer_url()))
    resp.set_cookie("inventera_lang", clean_lang, max_age=60 * 60 * 24 * 365)
    return resp


@settings_bp.route("/settings")
def settings():
    """Render the administrative settings page."""
    try:
        ha_url, ha_token, is_addon = get_ha_config()
        client = HomeAssistantTodoClient(ha_url, ha_token)

        connected = False
        conn_message = ""
        todo_entities = []

        if client.is_configured():
            connected, conn_message = client.test_connection()
            if connected:
                todo_entities = client.get_todo_entities()

        store_todo_map = get_store_todo_map()
        default_todo_entity = Settings.get("ha_default_todo_entity", "")
        remove_restocked_items = Settings.get("ha_remove_restocked_items", "false") == "true"
        managed_options = {field: get_managed_options(field) for field in OPTION_FIELDS}

        # Collect all stores from Store table and existing mappings
        stores = sorted(set(get_distinct_field_values("store")) | set(store_todo_map.keys()))

        return render_template(
            "settings.html",
            is_addon=is_addon,
            ha_url=ha_url,
            has_token=bool(ha_token),
            connected=connected,
            conn_message=conn_message,
            todo_entities=todo_entities,
            stores=stores,
            store_todo_map=store_todo_map,
            default_todo_entity=default_todo_entity,
            remove_restocked_items=remove_restocked_items,
            managed_options=managed_options,
            saved=request.args.get("saved") == "1",
            restored=request.args.get("restored") == "1",
        )
    except Exception:
        current_app.logger.exception("Error rendering settings page")
        return render_template("error.html", message=t("common.error_generic")), 500


@settings_bp.route("/settings/save", methods=["POST"])
def save_settings():
    """Persist Home Assistant connection, store mappings, and general settings atomically."""
    try:
        cfg_url, _, is_addon = get_ha_config()
        ha_url = (request.form.get("ha_url") or "").strip().rstrip("/")
        ha_token = (request.form.get("ha_token") or "").strip()
        default_todo = (request.form.get("ha_default_todo_entity") or "").strip()
        calendar_url = validate_calendar_url(request.form.get("calendar_url") or "")
        ha_lists_available = request.form.get("ha_lists_available", "1") == "1"

        # Validate standalone URL change requires explicit token
        if not is_addon and ha_url and ha_url != cfg_url and not ha_token:
            return (
                render_template("error.html", message=t("api.ha_token_required_for_url")),
                400,
            )

        # Validate & parse option CRUD payloads before mutating database
        parsed_options: dict[str, tuple[dict[int, str], list[str], list[int]]] = {}
        for field in OPTION_FIELDS:
            renames: dict[int, str] = {}
            prefix = f"opt_{field}_"
            for key, val in request.form.items():
                if key.startswith(prefix):
                    try:
                        opt_id = int(key[len(prefix) :])
                    except ValueError as exc:
                        raise ValueError(f"Invalid option ID for {field}: {key}") from exc
                    renames[opt_id] = val

            delete_ids: list[int] = []
            raw_del = request.form.get(f"opt_del_{field}")
            if raw_del:
                parsed_del = json.loads(raw_del)
                if not isinstance(parsed_del, list):
                    raise ValueError(f"Invalid delete list for {field}")
                delete_ids = [int(x) for x in parsed_del]

            new_names: list[str] = []
            raw_new = request.form.get(f"opt_new_{field}")
            if raw_new:
                parsed_new = json.loads(raw_new)
                if not isinstance(parsed_new, list):
                    raise ValueError(f"Invalid new options list for {field}")
                new_names = [str(x) for x in parsed_new]

            parsed_options[field] = (renames, new_names, delete_ids)

        # Apply all changes within a single transaction
        if not is_addon:
            if ha_url:
                Settings.set("ha_url", ha_url)
            if ha_token:
                Settings.set("ha_token", ha_token)

        if ha_lists_available or default_todo:
            Settings.set("ha_default_todo_entity", default_todo)
        Settings.set(
            "ha_remove_restocked_items",
            "true" if request.form.get("ha_remove_restocked_items") == "on" else "false",
        )
        Settings.set("calendar_url", calendar_url)

        if ha_lists_available:
            new_map = {}
            for key, value in request.form.items():
                if key.startswith("store_map_"):
                    store_name = key[len("store_map_") :]
                    if store_name and value.strip():
                        new_map[store_name] = value.strip()
            save_store_todo_map(new_map)
        else:
            existing_map = get_store_todo_map()
            for key, value in request.form.items():
                if key.startswith("store_map_"):
                    store_name = key[len("store_map_") :]
                    if store_name and value.strip():
                        existing_map[store_name] = value.strip()
            save_store_todo_map(existing_map)

        for field, (renames, new_names, delete_ids) in parsed_options.items():
            save_managed_options_crud(field, renames, new_names, delete_ids)

        db.session.commit()
        return redirect(url_for("settings.settings", saved="1"))
    except ValueError as e:
        db.session.rollback()
        current_app.logger.warning(f"Validation error saving settings: {e}")
        return render_template("error.html", message=str(e)), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error saving settings")
        return render_template("error.html", message=t("common.error_generic")), 500


@settings_bp.route("/settings/test_ha", methods=["POST"])
def test_ha():
    """Test Home Assistant connection and return discovered todo.* entities as JSON."""
    try:
        cfg_url, cfg_token, is_addon = get_ha_config()
        if is_addon:
            # In add-on mode, Supervisor URL & token are fixed and never sent to user-supplied URLs
            ha_url, ha_token = cfg_url, cfg_token
        else:
            submitted_url = (request.form.get("ha_url") or "").strip().rstrip("/")
            submitted_token = (request.form.get("ha_token") or "").strip()
            ha_url = submitted_url or cfg_url

            if submitted_url and submitted_url != cfg_url and not submitted_token:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": t("api.ha_token_required_for_url"),
                            "todo_entities": [],
                        }
                    ),
                    400,
                )
            ha_token = submitted_token or cfg_token

        client = HomeAssistantTodoClient(ha_url, ha_token)
        ok, msg = client.test_connection()
        entities = client.get_todo_entities() if ok else []

        return jsonify(
            {"status": "success" if ok else "error", "message": msg, "todo_entities": entities}
        )
    except Exception as e:
        current_app.logger.exception("Error testing Home Assistant connection")
        return jsonify({"status": "error", "message": str(e), "todo_entities": []}), 500


@settings_bp.route("/settings/backup")
def download_backup():
    """Download a JSON backup of inventory items, options, and non-secret settings."""
    payload = export_backup_payload()
    stamp = utc_now().strftime("%Y%m%d-%H%M%S")
    filename = f"inventera-backup-{stamp}.json"
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@settings_bp.route("/settings/restore", methods=["POST"])
def restore_backup():
    """Restore inventory items, options, and non-secret settings from an uploaded JSON backup."""
    try:
        uploaded = request.files.get("backup_file")
        if not uploaded or not uploaded.filename:
            raise ValueError("No backup file uploaded")
        raw = uploaded.read().decode("utf-8")
        payload = json.loads(raw)
        restore_backup_payload(payload)
        db.session.commit()
        return redirect(url_for("settings.settings", restored="1"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
        db.session.rollback()
        current_app.logger.warning(f"Invalid backup restore attempt: {e}")
        return render_template("error.html", message=str(e)), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error restoring backup")
        return render_template("error.html", message=t("common.error_generic")), 500

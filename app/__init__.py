"""
Inventera - Simple inventory management application.
Main application package.
"""

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import DEFAULT_INGRESS_PROXY, build_config
from app.extensions import csrf, db, migrate
from app.utils.responses import is_ajax_request

PUBLIC_DIRECT_ENDPOINTS = frozenset(
    {
        "main.index",
        "inventory.update_quantity",
        "settings.set_language",
        "static",
    }
)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """Enforce foreign key constraints on every SQLite connection."""
    module_name = type(dbapi_connection).__module__
    if module_name.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class IngressMiddleware:
    """
    WSGI middleware for Home Assistant Ingress (X-Ingress-Path).
    In add-on mode (SUPERVISOR_TOKEN set), restricts access to trusted Ingress proxy IPs
    unless overridden by INGRESS_TRUSTED_PROXIES or disabled in test config.
    """

    def __init__(
        self,
        wsgi_app,
        *,
        enforce_trusted_proxy: bool = False,
        trusted_proxies: set[str] | None = None,
    ):
        self.wsgi_app = wsgi_app
        self.enforce_trusted_proxy = enforce_trusted_proxy
        self.trusted_proxies = trusted_proxies or {DEFAULT_INGRESS_PROXY}

    def __call__(self, environ, start_response):
        remote_addr = (environ.get("REMOTE_ADDR") or "").strip()
        is_trusted_ingress = not self.enforce_trusted_proxy or (remote_addr in self.trusted_proxies)
        environ["inventera.is_ingress"] = is_trusted_ingress

        if is_trusted_ingress:
            ingress_path = (environ.get("HTTP_X_INGRESS_PATH") or "").strip()
            if ingress_path:
                normalized = "/" + ingress_path.strip("/")
                if normalized != "/":
                    environ["SCRIPT_NAME"] = normalized
                    path_info = environ.get("PATH_INFO", "")
                    if path_info == normalized:
                        environ["PATH_INFO"] = "/"
                    elif path_info.startswith(normalized + "/"):
                        environ["PATH_INFO"] = path_info[len(normalized) :]
        else:
            # Strip spoofed Ingress headers on untrusted direct requests
            environ.pop("HTTP_X_INGRESS_PATH", None)

        return self.wsgi_app(environ, start_response)


def create_app(test_config=None):
    """Application factory function."""
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)

    app_root = Path(__file__).resolve().parent
    app.config.update(build_config(app_root, test_config))

    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    proxied = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    raw_trusted = os.environ.get("INGRESS_TRUSTED_PROXIES", DEFAULT_INGRESS_PROXY)
    trusted_proxies = {ip.strip() for ip in raw_trusted.split(",") if ip.strip()}
    app.wsgi_app = IngressMiddleware(  # type: ignore[method-assign]
        proxied,
        enforce_trusted_proxy=bool(app.config.get("ENFORCE_INGRESS_PROXY", False)),
        trusted_proxies=trusted_proxies,
    )

    from app.controllers.inventory import inventory_bp
    from app.controllers.main import main_bp
    from app.controllers.settings import settings_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(settings_bp)

    from app.models.settings import Settings
    from app.utils.i18n import SUPPORTED_LANGUAGES, get_locale, get_translations_dict, t

    @app.before_request
    def restrict_direct_access():
        if app.config.get("ENFORCE_INGRESS_PROXY", False) and not request.environ.get(
            "inventera.is_ingress", False
        ):
            if request.endpoint not in PUBLIC_DIRECT_ENDPOINTS:
                msg = "Åtkomst nekad. Öppna via Home Assistant för att nå denna sida."
                if is_ajax_request():
                    return jsonify({"status": "error", "message": msg}), 403
                return render_template("error.html", message=msg), 403
        return None

    @app.context_processor
    def inject_globals():
        lang = get_locale()
        is_direct_public = (app.config.get("ENFORCE_INGRESS_PROXY") is True) and (
            request.environ.get("inventera.is_ingress") is not True
        )
        try:
            calendar_url = Settings.get("calendar_url", os.environ.get("CALENDAR_URL", ""))
        except Exception:
            calendar_url = os.environ.get("CALENDAR_URL", "")
        return {
            "t": t,
            "current_lang": lang,
            "supported_languages": SUPPORTED_LANGUAGES,
            "js_translations": get_translations_dict(lang),
            "calendar_url": calendar_url,
            "is_direct_public": is_direct_public,
        }

    # Import models so Flask-Migrate / Alembic discovers all metadata
    from app.models import item as _item_models  # noqa: F401
    from app.models import settings as _settings_models  # noqa: F401

    app.logger.info("Application initialized successfully")
    return app

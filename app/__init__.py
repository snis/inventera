"""
Inventera - Simple inventory management application.
Main application package.
"""

import logging
import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.wrappers import Response

# Initialize SQLAlchemy instance
db = SQLAlchemy()

DEFAULT_INGRESS_PROXY = "172.30.32.2"


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
        if self.enforce_trusted_proxy and remote_addr not in self.trusted_proxies:
            resp = Response("Forbidden: direct access disabled in Ingress mode", status=403)
            return resp(environ, start_response)

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

        return self.wsgi_app(environ, start_response)


def create_app(test_config=None):
    """
    Application factory function.
    Creates and configures the Flask application.
    """
    app = Flask(__name__)

    # Configure logging
    app.logger.setLevel(logging.INFO)

    # Default configuration
    db_path = "../instance/db.sqlite3"
    # Check if database exists, if not try to use the test database
    if not os.path.exists(os.path.join(os.path.dirname(__file__), db_path)):
        app.logger.warning(f"Database not found at {db_path}, attempting to create one")
        # The database will be created by db.create_all() below

    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_SORT_KEYS"] = False  # Preserve JSON order for readability
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", os.urandom(24).hex()
    )  # For session support

    # Override with test config if provided
    if test_config:
        app.config.update(test_config)

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # Initialize extensions with app
    db.init_app(app)

    # Enable ProxyFix for reverse proxies (NPM, Traefik) and explicit IngressMiddleware for HA Ingress
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    is_addon = bool(os.environ.get("SUPERVISOR_TOKEN", "").strip())
    enforce_proxy = bool(app.config.get("ENFORCE_INGRESS_PROXY", is_addon))
    raw_trusted = os.environ.get("INGRESS_TRUSTED_PROXIES", DEFAULT_INGRESS_PROXY)
    trusted_proxies = {ip.strip() for ip in raw_trusted.split(",") if ip.strip()}
    app.wsgi_app = IngressMiddleware(
        app.wsgi_app,
        enforce_trusted_proxy=enforce_proxy,
        trusted_proxies=trusted_proxies,
    )

    # Register blueprints
    from app.controllers.inventory import inventory_bp
    from app.controllers.main import main_bp
    from app.controllers.settings import settings_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(settings_bp)

    # Register i18n and dynamic settings in template context
    from app.models.settings import Settings
    from app.utils.i18n import SUPPORTED_LANGUAGES, get_locale, get_translations_dict, t

    @app.context_processor
    def inject_globals():
        lang = get_locale()
        calendar_url = ""
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
        }

    # Create database tables if they don't exist and backfill ID-backed options
    with app.app_context():
        db.create_all()
        from app.utils.helpers import ensure_option_schema_and_backfill

        ensure_option_schema_and_backfill()

    app.logger.info("Application initialized successfully")
    return app

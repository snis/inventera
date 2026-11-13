"""
Inventera - Simple inventory management application.
Main application package.
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import logging

# Initialize SQLAlchemy instance
db = SQLAlchemy()

def create_app(test_config=None):
    """
    Application factory function.
    Creates and configures the Flask application.
    """
    app = Flask(__name__)
    
    # Configure logging
    app.logger.setLevel(logging.INFO)
    
    # Default configuration
    db_path = '../instance/db.sqlite3'
    # Check if database exists, if not try to use the test database
    if not os.path.exists(os.path.join(os.path.dirname(__file__), db_path)):
        app.logger.warning(f"Database not found at {db_path}, attempting to create one")
        # The database will be created by db.create_all() below
    
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JSON_SORT_KEYS'] = False  # Preserve JSON order for readability
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())  # For session support
    
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

    # Enable ProxyFix for reverse proxies (NPM, Traefik) and Home Assistant Ingress
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_prefix=1
    )
    
    # Register blueprints
    from app.controllers.main import main_bp
    from app.controllers.inventory import inventory_bp
    from app.controllers.settings import settings_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(settings_bp)

    # Register i18n and dynamic settings in template context
    from app.utils.i18n import t, get_locale, get_translations_dict, SUPPORTED_LANGUAGES
    from app.models.settings import Settings

    @app.context_processor
    def inject_globals():
        lang = get_locale()
        calendar_url = ''
        try:
            calendar_url = Settings.get('calendar_url', os.environ.get('CALENDAR_URL', ''))
        except Exception:
            calendar_url = os.environ.get('CALENDAR_URL', '')
        return {
            't': t,
            'current_lang': lang,
            'supported_languages': SUPPORTED_LANGUAGES,
            'js_translations': get_translations_dict(lang),
            'calendar_url': calendar_url
        }
    
    # Create database tables if they don't exist
    with app.app_context():
        db.create_all()
    
    app.logger.info("Application initialized successfully")
    return app
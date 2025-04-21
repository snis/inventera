"""
Inventera - Simple inventory management application.
Main application package.
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
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
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///../instance/db.sqlite3'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JSON_SORT_KEYS'] = False  # Preserve JSON order for readability
    
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
    
    # Register blueprints
    from app.controllers.main import main_bp
    from app.controllers.inventory import inventory_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(inventory_bp)
    
    # Create database tables if they don't exist
    with app.app_context():
        db.create_all()
    
    app.logger.info("Application initialized successfully")
    return app
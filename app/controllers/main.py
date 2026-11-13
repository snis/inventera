"""
Main blueprint for the inventory application.
Contains routes for the main index page.
"""
from flask import Blueprint, render_template, current_app
from datetime import datetime
from app import db
from app.models.item import Item
from app.utils.helpers import (
    get_items_by_category,
    get_items_by_location,
    get_row_color,
    get_warning_color
)

# Create blueprint
main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@main_bp.route('/index')
@main_bp.route('/index/<int:page>')
def index(page: int = 1):
    """
    Render the main index page showing inventory items grouped by location
    with collapsible sections.
    """
    try:
        items_by_location = get_items_by_location()
        total_items = db.session.query(Item).count()
        
        return render_template(
            'index.html',
            items_by_location=items_by_location,
            get_row_color=get_row_color,
            get_warning_color=get_warning_color,
            now=datetime.now(),
            total_items=total_items
        )
    except Exception as e:
        current_app.logger.error(f"Error rendering index: {str(e)}")
        return render_template('error.html', message="Ett fel uppstod vid hämtning av data.")
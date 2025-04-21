"""
Main blueprint for the inventory application.
Contains routes for the main index page.
"""
from flask import Blueprint, render_template, current_app
from datetime import datetime
from app import db
from app.models.item import Item
from app.utils.helpers import get_items_by_category, get_row_color, get_warning_color

# Create blueprint
main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@main_bp.route('/index')
@main_bp.route('/index/<int:page>')
def index(page: int = 1):
    """
    Render the main index page showing inventory items with pagination.
    
    Args:
        page: The page number to display (default: 1)
    
    Returns:
        Rendered index template
    """
    try:
        items_per_page = 50  # Default from requirements
        
        # Get items for the current page
        items_by_category = get_items_by_category(page=page, items_per_page=items_per_page)
        
        # Count total items for pagination
        total_items = db.session.query(Item).count()
        total_pages = (total_items + items_per_page - 1) // items_per_page
        
        return render_template(
            'index.html',
            items_by_category=items_by_category,
            get_row_color=get_row_color,
            get_warning_color=get_warning_color,
            now=datetime.now(),
            pagination={
                'page': page,
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages,
                'total_items': total_items
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error rendering index: {str(e)}")
        # Return a simple error page if something goes wrong
        return render_template('error.html', message="Ett fel uppstod vid hämtning av data.")
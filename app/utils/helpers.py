"""
Helper functions for the inventory application.
"""
from datetime import datetime
from typing import Dict, List, Optional
from app.models.item import Item
from app import db


def get_row_color(last_checked: Optional[datetime]) -> str:
    """
    Determine row color based on when an item was last checked.
    
    Args:
        last_checked: Datetime when item was last checked
        
    Returns:
        String with color code
    """
    if last_checked:
        # Calculate the difference in days
        days_difference = (datetime.now() - last_checked).days

        # Define color-coding logic with non-overlapping ranges
        if days_difference < 1:
            return '#00ff00aa'  # green
        elif 1 <= days_difference < 4:
            return '#ff9800aa'  # orange (varningsfärg)
        elif 4 <= days_difference <= 8:
            return '#ff8c00aa'  # darkorange
        else:
            return '#ff0000aa'  # red
    else:
        return 'grey'


def get_warning_color(quantity: Optional[int], alert_quantity: Optional[int]) -> str:
    """
    Determine warning color based on quantity relative to alert threshold.
    
    Args:
        quantity: Current quantity of item
        alert_quantity: Alert threshold for item
        
    Returns:
        String with color code
    """
    if quantity is not None and alert_quantity is not None:
        quantity_difference = quantity - alert_quantity
        if quantity_difference == 0:
            return '#ff9800aa'  # Mer orangeaktig varningsfärg
        elif quantity_difference < 0:
            return '#ff0000aa'  # Röd för kritiskt
        else:
            return '#00ff00aa'  # Grön för OK
    else:
        return 'grey'


def get_items_by_category(page: int = 1, items_per_page: int = 50) -> Dict[str, List[Item]]:
    """
    Get all items organized by category with optional pagination.
    
    Args:
        page: The page number to fetch (default: 1)
        items_per_page: Number of items per page (default: 50)
        
    Returns:
        Dictionary with categories as keys and lists of items as values
    """
    # Validate inputs
    if not isinstance(page, int) or page < 1:
        page = 1
    
    if not isinstance(items_per_page, int) or items_per_page < 1:
        items_per_page = 50
    
    # Get all distinct categories
    categories = Item.query.with_entities(Item.category).distinct()
    items_by_category = {}
    total_items = 0
    
    try:
        for category in categories:
            if not category or not category[0]:
                continue  # Skip empty categories
                
            cat_name = category[0]
            # Get all items for the category
            query = Item.query.filter_by(category=cat_name).order_by(Item.name)
            
            # If pagination is enabled (items_per_page > 0)
            if items_per_page > 0:
                # Calculate total items for calculating pagination info
                category_count = query.count()
                total_items += category_count
                
                # Apply pagination to the query
                items = query.limit(items_per_page).offset((page - 1) * items_per_page).all()
            else:
                # No pagination
                items = query.all()
            
            if items:  # Only add category if there are items in the current page
                items_by_category[cat_name] = items
    except Exception as e:
        # Log error but continue with an empty result rather than breaking the page
        import logging
        logging.error(f"Error in get_items_by_category: {str(e)}")
        return {}
    
    return items_by_category
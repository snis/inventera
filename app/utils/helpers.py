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

        # Define color-coding logic with non-overlapping ranges using HA theme CSS variables
        if days_difference < 1:
            return 'var(--inv-green)'
        elif 1 <= days_difference < 4:
            return 'var(--inv-orange)'
        elif 4 <= days_difference <= 8:
            return 'var(--inv-darkorange)'
        else:
            return 'var(--inv-red)'
    else:
        return 'var(--inv-grey)'


def get_warning_color(quantity: Optional[int], alert_quantity: Optional[int]) -> str:
    """
    Determine warning color based on quantity relative to alert threshold.
    
    Args:
        quantity: Current quantity of item
        alert_quantity: Alert threshold for item
        
    Returns:
        String with CSS variable color code
    """
    if quantity is not None and alert_quantity is not None:
        quantity_difference = quantity - alert_quantity
        if quantity_difference == 0:
            return 'var(--inv-orange)'  # Varningsfärg
        elif quantity_difference < 0:
            return 'var(--inv-red)'  # Röd för kritiskt / av
        else:
            return 'var(--inv-green)'  # Grön för OK / på
    else:
        return 'var(--inv-grey)'


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


def get_items_by_location() -> Dict[str, List[Item]]:
    """
    Get all items grouped by their physical location, sorted dynamically.
    
    Returns:
        Dictionary with location names as keys and sorted lists of items as values.
    """
    from app.utils.i18n import t
    other_label = t('common.other')
    try:
        items = Item.query.order_by(Item.name).all()
        grouped: Dict[str, List[Item]] = {}
        
        for item in items:
            loc = (item.location or '').strip() or other_label
            if loc not in grouped:
                grouped[loc] = []
            grouped[loc].append(item)
            
        ordered_grouped: Dict[str, List[Item]] = {}
        for loc in sorted(k for k in grouped.keys() if k != other_label):
            ordered_grouped[loc] = grouped[loc]
        if other_label in grouped:
            ordered_grouped[other_label] = grouped[other_label]
            
        return ordered_grouped
    except Exception as e:
        import logging
        logging.error(f"Error in get_items_by_location: {str(e)}")
        return {}


def get_low_stock_by_store() -> Dict[str, List[Item]]:
    """
    Get all items that need to be reordered (quantity <= alert_quantity),
    grouped by store / purchasing channel, sorted dynamically.
    
    Returns:
        Dictionary with store names as keys and lists of items needing restock.
    """
    from app.utils.i18n import t
    other_label = t('common.other')
    try:
        items = Item.query.filter(Item.quantity <= Item.alert_quantity).order_by(Item.name).all()
        grouped: Dict[str, List[Item]] = {}
        
        for item in items:
            store = (item.store or '').strip() or other_label
            if store not in grouped:
                grouped[store] = []
            grouped[store].append(item)
            
        ordered_grouped: Dict[str, List[Item]] = {}
        for store in sorted(k for k in grouped.keys() if k != other_label):
            ordered_grouped[store] = grouped[store]
        if other_label in grouped:
            ordered_grouped[other_label] = grouped[other_label]
            
        return ordered_grouped
    except Exception as e:
        import logging
        logging.error(f"Error in get_low_stock_by_store: {str(e)}")
        return {}


def get_distinct_field_values(field_name: str) -> List[str]:
    """Return sorted distinct non-empty values for a given Item string column."""
    try:
        col = getattr(Item, field_name)
        rows = db.session.query(col).distinct().all()
        return sorted({r[0].strip() for r in rows if r and r[0] and r[0].strip()})
    except Exception:
        return []

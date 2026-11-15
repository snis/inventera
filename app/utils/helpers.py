"""
Helper functions for the inventory application.
"""
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy import text
from app.models.item import Item, Unit, Location, Store
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


OPTION_FIELDS = ('unit', 'location', 'store')
OPTION_MODELS = {
    'unit': Unit,
    'location': Location,
    'store': Store,
}


def get_distinct_field_values(field_name: str) -> List[str]:
    """Return sorted distinct non-empty values for a given Item string column."""
    if field_name in OPTION_MODELS:
        model = OPTION_MODELS[field_name]
        return [row.name for row in model.query.order_by(db.func.lower(model.name)).all()]
    try:
        col = getattr(Item, field_name)
        rows = db.session.query(col).distinct().all()
        return sorted({r[0].strip() for r in rows if r and r[0] and r[0].strip()})
    except Exception:
        return []


def get_or_create_option(field_name: str, name: str):
    """Fetch existing option row (case-insensitive) or create a new one."""
    clean = (name or '').strip()
    if not clean:
        return None
    model = OPTION_MODELS[field_name]
    existing = model.query.filter(db.func.lower(model.name) == clean.lower()).first()
    if existing:
        return existing
    created = model(name=clean)
    db.session.add(created)
    db.session.flush()
    return created


def ensure_option_schema_and_backfill() -> None:
    """Add unit_id/location_id/store_id columns if missing and backfill from existing items/settings."""
    from app.models.settings import Settings
    import json

    cols = {row[1] for row in db.session.execute(text("PRAGMA table_info(item)")).fetchall()}
    for col_name in ('unit_id', 'location_id', 'store_id'):
        if col_name not in cols:
            db.session.execute(text(f"ALTER TABLE item ADD COLUMN {col_name} INTEGER"))
    db.session.commit()

    # Seed any previously saved Settings managed_options_<field>
    for field in OPTION_FIELDS:
        raw = Settings.get(f'managed_options_{field}')
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    for val in parsed:
                        get_or_create_option(field, str(val))
            except (ValueError, TypeError):
                pass

    # Backfill Item foreign keys from existing string columns
    for item in Item.query.all():
        if item.unit_id is None and (item.unit or '').strip():
            opt = get_or_create_option('unit', item.unit)
            if opt:
                item.unit_id = opt.id
                item.unit = opt.name
        if item.location_id is None and (item.location or '').strip():
            opt = get_or_create_option('location', item.location)
            if opt:
                item.location_id = opt.id
                item.location = opt.name
        if item.store_id is None and (item.store or '').strip():
            opt = get_or_create_option('store', item.store)
            if opt:
                item.store_id = opt.id
                item.store = opt.name
    db.session.commit()


def get_managed_options(field_name: str):
    """Return all option rows (with .id and .name) for a field sorted by name."""
    model = OPTION_MODELS[field_name]
    return model.query.order_by(db.func.lower(model.name)).all()


def save_managed_options_crud(
    field_name: str,
    renames: Dict[int, str],
    new_names: List[str],
    delete_ids: List[int],
) -> None:
    """Apply renames, additions, and deletions for Unit/Location/Store by ID and sync Items."""
    model = OPTION_MODELS[field_name]
    fk_col = f'{field_name}_id'

    # Handle deletions first
    for opt_id in delete_ids:
        opt = model.query.get(opt_id)
        if opt:
            Item.query.filter(getattr(Item, fk_col) == opt.id).update(
                {fk_col: None, field_name: ''}, synchronize_session=False
            )
            db.session.delete(opt)
    db.session.flush()

    # Handle renames by ID (update option name + sync Item string column + store_todo_map)
    store_renames: Dict[str, str] = {}
    for opt_id, new_name in renames.items():
        clean = (new_name or '').strip()
        if not clean:
            continue
        opt = model.query.get(opt_id)
        if not opt or opt.name == clean:
            continue
        conflict = model.query.filter(
            db.func.lower(model.name) == clean.lower(), model.id != opt.id
        ).first()
        if conflict:
            # Merge items into existing target option
            Item.query.filter(getattr(Item, fk_col) == opt.id).update(
                {fk_col: conflict.id, field_name: conflict.name}, synchronize_session=False
            )
            if field_name == 'store':
                store_renames[opt.name] = conflict.name
            db.session.delete(opt)
        else:
            old_name = opt.name
            opt.name = clean
            Item.query.filter(getattr(Item, fk_col) == opt.id).update(
                {field_name: clean}, synchronize_session=False
            )
            if field_name == 'store':
                store_renames[old_name] = clean

    # Handle additions
    for name in new_names:
        get_or_create_option(field_name, name)

    db.session.commit()

    if store_renames:
        from app.utils.ha_todo import get_store_todo_map, save_store_todo_map
        todo_map = get_store_todo_map()
        changed = False
        for old_name, new_name in store_renames.items():
            if old_name in todo_map:
                if new_name not in todo_map:
                    todo_map[new_name] = todo_map[old_name]
                del todo_map[old_name]
                changed = True
        if changed:
            save_store_todo_map(todo_map)

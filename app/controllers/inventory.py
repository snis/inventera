"""
Inventory blueprint for the inventory application.
Contains routes for inventory management operations.
"""
from flask import Blueprint, request, jsonify, redirect, url_for, current_app, render_template
from datetime import datetime
from typing import Dict, Any

from app import db
from app.models.item import Item, Unit, Location, Store
from app.utils.helpers import (
    get_items_by_category,
    get_items_by_location,
    get_low_stock_by_store,
    get_managed_options,
    get_row_color,
    get_warning_color
)
from app.utils.responses import create_response, is_ajax_request
from app.utils.ha_todo import sync_low_inventory_to_ha
from app.utils.i18n import t

# Create blueprint
inventory_bp = Blueprint('inventory', __name__)


@inventory_bp.route('/shopping')
def shopping():
    """
    Render shopping list view grouped by store/supplier for all items needing restock.
    """
    try:
        low_stock = get_low_stock_by_store()
        return render_template(
            'shopping.html',
            low_stock_by_store=low_stock
        )
    except Exception as e:
        current_app.logger.error(f"Error rendering shopping list: {str(e)}")
        return render_template('error.html', message="Ett fel uppstod vid hämtning av inköpslistor.")


@inventory_bp.route('/sync_ha', methods=['POST'])
def sync_ha():
    """
    Sync all items below safety threshold to Home Assistant Todo lists.
    """
    try:
        result = sync_low_inventory_to_ha()
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error syncing to Home Assistant: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"Ett fel uppstod: {str(e)}"
        }), 500


@inventory_bp.route('/update_quantity', methods=['POST'])
def update_quantity():
    """
    Update the quantity of an inventory item.
    
    Returns:
        JSON response for AJAX requests, redirect to index for non-AJAX requests
    """
    try:
        item_id = int(request.form.get('item_id'))
        new_quantity = request.form.get('new_quantity')

        # Check if new_quantity is not None and can be converted to an integer
        if new_quantity is not None and new_quantity.strip().isdigit():
            new_quantity = int(new_quantity)
        else:
            current_app.logger.warning(f"Invalid quantity: item_id: {item_id}, new_quantity: {new_quantity}")
            return create_response(
                success=False,
                message=t('api.invalid_quantity'),
                redirect_url=url_for('main.index')
            )

        # Update the item in the database
        item = Item.query.get(item_id)
        if not item:
            current_app.logger.warning(f"Item not found: {item_id}")
            return create_response(
                success=False,
                message=t('api.item_not_found'),
                redirect_url=url_for('main.index')
            )
        
        # Update item data
        item.quantity = new_quantity
        item.last_checked = datetime.now()
        db.session.commit()
        
        # If AJAX request, return detailed JSON
        if is_ajax_request():
            row_color = get_row_color(item.last_checked)
            warning_color = get_warning_color(item.quantity, item.alert_quantity)
            
            return jsonify({
                'status': 'success',
                'item_id': item_id,
                'new_quantity': new_quantity,
                'last_checked': item.last_checked.strftime('%d/%m'),
                'row_color': row_color,
                'warning_color': warning_color,
                'button_class': ""  # Empty since it's recently updated
            })

        # If regular form submit, redirect to index
        return redirect(url_for('main.index'))
    
    except Exception as e:
        current_app.logger.error(f"Error updating quantity: {str(e)}")
        return create_response(
            success=False,
            message='Ett fel uppstod',
            redirect_url=url_for('main.index')
        )


@inventory_bp.route('/inventory')
@inventory_bp.route('/inventory/<int:page>')
def inventory(page: int = 1):
    """
    Render the inventory management page with pagination.
    
    Args:
        page: The page number to display (default: 1)
    
    Returns:
        Rendered inventory template
    """
    try:
        items_per_page = 50  # Default from requirements

        sort_by = request.args.get('sort', 'location')
        if sort_by not in ('name', 'location', 'store'):
            sort_by = 'location'
        sort_dir = request.args.get('dir', 'asc')
        if sort_dir not in ('asc', 'desc'):
            sort_dir = 'asc'

        sort_columns = {
            'name': db.func.lower(Item.name),
            'location': db.func.lower(db.func.coalesce(Item.location, '')),
            'store': db.func.lower(db.func.coalesce(Item.store, '')),
        }
        primary_col = sort_columns[sort_by]
        primary_order = primary_col.desc() if sort_dir == 'desc' else primary_col.asc()

        # Sort by chosen column (default: location), with item name as secondary sort
        query = Item.query.order_by(primary_order, db.func.lower(Item.name).asc())
        total_items = query.count()
        total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
        items = query.limit(items_per_page).offset((page - 1) * items_per_page).all()

        return render_template(
            'inventory.html',
            items=items,
            sort_by=sort_by,
            sort_dir=sort_dir,
            distinct_units=get_managed_options('unit'),
            distinct_locations=get_managed_options('location'),
            distinct_stores=get_managed_options('store'),
            get_row_color=get_row_color,
            get_warning_color=get_warning_color,
            pagination={
                'page': page,
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages,
                'total_items': total_items
            }
        )
    except Exception as e:
        current_app.logger.error(f"Error rendering inventory page: {str(e)}")
        # Log the full traceback for debugging
        import traceback
        current_app.logger.error(f"Traceback: {traceback.format_exc()}")
        return render_template('error.html', message="Ett fel uppstod vid hämtning av data.")


@inventory_bp.route('/update_items', methods=['POST'])
def update_items():
    """
    Update or add inventory items.
    
    Returns:
        JSON response for AJAX requests, redirect to inventory for non-AJAX requests
    """
    try:
        # Handle item updates
        for key, value in request.form.items():
            if key.startswith('update_item'):
                item_id = int(value)
                item = Item.query.get(item_id)
                if item:
                    item.name = request.form.get(f'name_{item_id}')
                    quantity_str = request.form.get(f'quantity_{item_id}')
                    alert_quantity_str = request.form.get(f'alert_quantity_{item_id}')
                    
                    # Validate quantity and alert_quantity
                    if quantity_str and quantity_str.strip().isdigit():
                        item.quantity = int(quantity_str)
                    
                    if alert_quantity_str and alert_quantity_str.strip().isdigit():
                        item.alert_quantity = int(alert_quantity_str)
                    
                    unit_id_str = request.form.get(f'unit_{item_id}')
                    if unit_id_str and unit_id_str.isdigit():
                        unit_obj = Unit.query.get(int(unit_id_str))
                        if unit_obj:
                            item.unit_id = unit_obj.id
                            item.unit = unit_obj.name

                    loc_id_str = request.form.get(f'location_{item_id}')
                    if loc_id_str and loc_id_str.isdigit():
                        loc_obj = Location.query.get(int(loc_id_str))
                        if loc_obj:
                            item.location_id = loc_obj.id
                            item.location = loc_obj.name
                    elif loc_id_str == '':
                        item.location_id = None
                        item.location = ''

                    store_id_str = request.form.get(f'store_{item_id}')
                    if store_id_str and store_id_str.isdigit():
                        store_obj = Store.query.get(int(store_id_str))
                        if store_obj:
                            item.store_id = store_obj.id
                            item.store = store_obj.name
                    elif store_id_str == '':
                        item.store_id = None
                        item.store = ''

                    item.last_checked = datetime.now()
                    db.session.commit()

                    # AJAX response if requested
                    if is_ajax_request():
                        row_color = get_row_color(item.last_checked)
                        warning_color = get_warning_color(item.quantity, item.alert_quantity)
                        return jsonify({
                            'status': 'success',
                            'item_id': item_id,
                            'item': item.to_dict(),
                            'row_color': row_color,
                            'warning_color': warning_color
                        })

        # Handle item addition
        if 'add_item' in request.form:
            new_name = (request.form.get('new_name') or '').strip()
            new_quantity_str = request.form.get('new_quantity')
            new_alert_quantity_str = request.form.get('new_alert_quantity')
            new_unit_id_str = request.form.get('new_unit')
            new_location_id_str = request.form.get('new_location')
            new_store_id_str = request.form.get('new_store')

            unit_obj = Unit.query.get(int(new_unit_id_str)) if (new_unit_id_str and new_unit_id_str.isdigit()) else None
            loc_obj = Location.query.get(int(new_location_id_str)) if (new_location_id_str and new_location_id_str.isdigit()) else None
            store_obj = Store.query.get(int(new_store_id_str)) if (new_store_id_str and new_store_id_str.isdigit()) else None

            # Validate inputs
            if not new_name or not unit_obj:
                return create_response(
                    success=False,
                    message=t('api.missing_fields'),
                    redirect_url=url_for('inventory.inventory')
                )

            new_quantity = 0
            new_alert_quantity = 0

            # Validate quantity and alert_quantity
            if new_quantity_str and new_quantity_str.strip().isdigit():
                new_quantity = int(new_quantity_str)

            if new_alert_quantity_str and new_alert_quantity_str.strip().isdigit():
                new_alert_quantity = int(new_alert_quantity_str)

            # Create new item
            new_item = Item(
                name=new_name,
                quantity=new_quantity,
                alert_quantity=new_alert_quantity,
                unit=unit_obj.name,
                unit_id=unit_obj.id,
                category='',
                location=loc_obj.name if loc_obj else '',
                location_id=loc_obj.id if loc_obj else None,
                store=store_obj.name if store_obj else '',
                store_id=store_obj.id if store_obj else None,
                last_checked=datetime.now()
            )
            db.session.add(new_item)

        db.session.commit()
        
        # AJAX response for add_item
        if 'add_item' in request.form and is_ajax_request():
            return jsonify({
                'status': 'success',
                'message': 'Artikel tillagd'
            })

        return redirect(url_for('inventory.inventory'))
    
    except Exception as e:
        current_app.logger.error(f"Error updating items: {str(e)}")
        return create_response(
            success=False,
            message='Ett fel uppstod',
            redirect_url=url_for('inventory.inventory')
        )


@inventory_bp.route('/remove_item/<int:item_id>', methods=['POST'])
def remove_item(item_id):
    """
    Remove an inventory item.
    
    Args:
        item_id: ID of the item to remove
        
    Returns:
        JSON response for AJAX requests, redirect to inventory for non-AJAX requests
    """
    try:
        current_app.logger.info(f"Removing item with ID: {item_id}")
        item = Item.query.get(item_id)
        if item:
            item_name = item.name
            db.session.delete(item)
            db.session.commit()
            
            if is_ajax_request():
                return jsonify({'status': 'success', 'message': f'Artikel {item_name} borttagen'})
        else:
            if is_ajax_request():
                return jsonify({'status': 'error', 'message': 'Artikel hittades inte'})
                
        return redirect(url_for('inventory.inventory'))
    
    except Exception as e:
        current_app.logger.error(f"Error removing item: {str(e)}")
        return create_response(
            success=False,
            message='Ett fel uppstod',
            redirect_url=url_for('inventory.inventory')
        )


@inventory_bp.route('/toggle_visibility/<int:item_id>', methods=['POST'])
def toggle_visibility(item_id: int):
    """Toggle whether an item is visible on the Inventera and shopping list pages."""
    try:
        item = Item.query.get(item_id)
        if not item:
            return jsonify({'status': 'error', 'message': t('api.item_not_found')}), 404
        item.is_visible = not bool(item.is_visible)
        db.session.commit()
        return jsonify({
            'status': 'success',
            'item_id': item.id,
            'is_visible': bool(item.is_visible)
        })
    except Exception as e:
        current_app.logger.error(f"Error toggling visibility for {item_id}: {str(e)}")
        return jsonify({'status': 'error', 'message': t('common.error_generic')}), 500
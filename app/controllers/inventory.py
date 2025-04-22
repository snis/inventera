"""
Inventory blueprint for the inventory application.
Contains routes for inventory management operations.
"""
from flask import Blueprint, request, jsonify, redirect, url_for, current_app, render_template
from datetime import datetime
from typing import Dict, Any

from app import db
from app.models.item import Item
from app.utils.helpers import get_items_by_category, get_row_color, get_warning_color
from app.utils.responses import create_response, is_ajax_request

# Create blueprint
inventory_bp = Blueprint('inventory', __name__)


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
                message='Antal måste vara ett positivt heltal',
                redirect_url=url_for('main.index')
            )

        # Update the item in the database
        item = Item.query.get(item_id)
        if not item:
            current_app.logger.warning(f"Item not found: {item_id}")
            return create_response(
                success=False,
                message='Artikel hittades inte',
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
        
        # Get items for the current page
        items_by_category = get_items_by_category(page=page, items_per_page=items_per_page)
        
        # Count total items for pagination
        total_items = db.session.query(Item).count()
        total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)

        return render_template(
            'inventory.html',
            items_by_category=items_by_category,
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
                    
                    item.unit = request.form.get(f'unit_{item_id}')
                    item.category = request.form.get(f'category_{item_id}')
                    item.last_checked = datetime.now()
        
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
            new_name = request.form.get('new_name')
            new_quantity_str = request.form.get('new_quantity')
            new_alert_quantity_str = request.form.get('new_alert_quantity')
            new_unit = request.form.get('new_unit')
            new_category = request.form.get('new_category')
            
            # Validate inputs
            if not new_name or not new_unit or not new_category:
                return create_response(
                    success=False,
                    message='Alla fält måste fyllas i',
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
                unit=new_unit, 
                category=new_category,
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
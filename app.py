from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JSON_SORT_KEYS'] = False  # Preserve JSON order for readability

db = SQLAlchemy(app)


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), nullable=False, unique=True)
    category = db.Column(db.String(32), nullable=False)
    quantity = db.Column(db.Integer)
    unit = db.Column(db.String(16), nullable=False)
    alert_quantity = db.Column(db.Integer)
    last_checked = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Item: {self.name}>'
    
    def to_dict(self):
        """Convert item to dictionary for JSON responses"""
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'quantity': self.quantity,
            'unit': self.unit,
            'alert_quantity': self.alert_quantity,
            'last_checked': self.last_checked.strftime('%d/%m') if self.last_checked else None
        }


def get_row_color(last_checked):
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


def get_warning_color(quantity, alert_quantity):
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


def get_items_by_category():
    """Helper function to get all items organized by category"""
    categories = Item.query.with_entities(Item.category).distinct()
    items_by_category = {}

    for category in categories:
        items = Item.query.filter_by(
            category=category[0]).order_by(Item.name).all()
        items_by_category[category[0]] = items
    
    return items_by_category


@app.route('/')
@app.route('/index')
def index():
    items_by_category = get_items_by_category()
    
    return render_template(
        'index.html',
        items_by_category=items_by_category,
        get_row_color=get_row_color,
        get_warning_color=get_warning_color
    )


@app.route('/update_quantity', methods=['POST'])
def update_quantity():
    try:
        item_id = int(request.form.get('item_id'))
        new_quantity = request.form.get('new_quantity')

        # Check if new_quantity is not None and can be converted to an integer
        if new_quantity is not None and new_quantity.strip().isdigit():
            new_quantity = int(new_quantity)
        else:
            # Log the values for debugging
            app.logger.warning(f"Invalid quantity: item_id: {item_id}, new_quantity: {new_quantity}")
            error_response = {'status': 'error', 'message': 'Antal måste vara ett positivt heltal'}
            
            # Return JSON or redirect based on request type
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(error_response)
            return redirect(url_for('index'))

        # Update the item in the database
        item = Item.query.get(item_id)
        if not item:
            app.logger.warning(f"Item not found: {item_id}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'status': 'error', 'message': 'Artikel hittades inte'})
            return redirect(url_for('index'))
        
        # Update item data
        item.quantity = new_quantity
        item.last_checked = datetime.now()
        db.session.commit()
        
        # If AJAX request, return JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            row_color = get_row_color(item.last_checked)
            warning_color = get_warning_color(item.quantity, item.alert_quantity)
            return jsonify({
                'status': 'success',
                'item_id': item_id,
                'new_quantity': new_quantity,
                'last_checked': item.last_checked.strftime('%d/%m'),
                'row_color': row_color,
                'warning_color': warning_color
            })

        # If regular form submit, redirect to index
        return redirect(url_for('index'))
    
    except Exception as e:
        app.logger.error(f"Error updating quantity: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'Ett fel uppstod'})
        return redirect(url_for('index'))


@app.route('/inventory')
def inventory():
    items_by_category = get_items_by_category()

    return render_template(
        'inventory.html',
        items_by_category=items_by_category,
        get_row_color=get_row_color,
        get_warning_color=get_warning_color
    )


@app.route('/update_items', methods=['POST'])
def update_items():
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
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
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
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'status': 'error', 'message': 'Alla fält måste fyllas i'})
                return redirect(url_for('inventory'))
            
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
        if 'add_item' in request.form and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'status': 'success',
                'message': 'Artikel tillagd'
            })

        return redirect(url_for('inventory'))
    
    except Exception as e:
        app.logger.error(f"Error updating items: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'Ett fel uppstod'})
        return redirect(url_for('inventory'))


@app.route('/remove_item/<int:item_id>', methods=['POST'])
def remove_item(item_id):
    try:
        app.logger.info(f"Removing item with ID: {item_id}")
        item = Item.query.get(item_id)
        if item:
            db.session.delete(item)
            db.session.commit()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'status': 'success', 'message': f'Artikel {item.name} borttagen'})
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'status': 'error', 'message': 'Artikel hittades inte'})
                
        return redirect(url_for('inventory'))
    
    except Exception as e:
        app.logger.error(f"Error removing item: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'Ett fel uppstod'})
        return redirect(url_for('inventory'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0')

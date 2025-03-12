from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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


def get_row_color(last_checked):
    if last_checked:
        # Calculate the difference in days
        days_difference = (datetime.now() - last_checked).days

        # Define your color-coding logic here
        if days_difference < 1:
            return '#00ff00aa'  # green
        elif 1 <= days_difference <= 5:
            return '#adff2faa'  # greenyellow
        elif 4 <= days_difference <= 8:
            return '#ff8c00aa'  # darkorange
        else:
            return '#ff0000aa'  # red
    else:
        return 'grey'
    # or another default color for items without last_checked


def get_warning_color(quantity, alert_quantity):
    if quantity is not None and alert_quantity is not None:
        quantity_difference = quantity - alert_quantity
        if quantity_difference == 0:
            return '#adff2faa'
        elif quantity_difference < 0:
            return '#ff0000aa'
        else:
            return '#00ff00aa'
    else:
        return 'grey'


@app.route('/')
@app.route('/index')
def index():
    categories = Item.query.with_entities(Item.category).distinct()
    items_by_category = {}

    for category in categories:
        items = Item.query.filter_by(
            category=category[0]).order_by(Item.name).all()
        items_by_category[category[0]] = items

    return render_template(
        'index.html',
        items_by_category=items_by_category,
        get_row_color=get_row_color,
        get_warning_color=get_warning_color
    )


@app.route('/update_quantity', methods=['POST'])
def update_quantity():
    item_id = int(request.form.get('item_id'))
    new_quantity = request.form.get('new_quantity')

    # Check if new_quantity is not None and can be converted to an integer
    if new_quantity is not None and new_quantity.isdigit():
        new_quantity = int(new_quantity)
    else:
        # Log the values for debugging
        print(f"item_id: {item_id}, new_quantity: {new_quantity}")

        # Handle the case where new_quantity is None or not a valid integer
        return jsonify({'status': 'error', 'message': 'Invalid new_quantity'})

    # Update the item in the database
    item = Item.query.get(item_id)
    if item:
        item.quantity = new_quantity
        # Assuming 'last_checked' is a DateTime field in your Item model
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

    db.session.commit()

    # If regular form submit, redirect to index
    return redirect(url_for('index'))


@app.route('/inventory')
def inventory():
    items_by_category = {}

    # Fetch distinct categories
    categories = Item.query.with_entities(Item.category).distinct()

    # Fetch items for each category and store them in the dictionary
    for category in categories:
        items = Item.query.filter_by(
            category=category[0]).order_by(Item.name).all()
        items_by_category[category[0]] = items

    return render_template(
        'inventory.html',
        items_by_category=items_by_category,
        get_row_color=get_row_color,
        get_warning_color=get_warning_color
    )


@app.route('/update_items', methods=['POST'])
def update_items():
    # Handle item updates
    for key, value in request.form.items():
        if key.startswith('update_item'):
            item_id = int(value)
            item = Item.query.get(item_id)
            if item:
                item.name = request.form.get(f'name_{item_id}')
                item.quantity = int(request.form.get(f'quantity_{item_id}'))
                item.alert_quantity = int(
                    request.form.get(f'alert_quantity_{item_id}')
                )
                item.unit = request.form.get(f'unit_{item_id}')
                item.category = request.form.get(f'category_{item_id}')

    # Handle item addition
    if 'add_item' in request.form:
        new_name = request.form.get('new_name')
        new_quantity = int(request.form.get('new_quantity'))
        new_alert_quantity = int(request.form.get('new_alert_quantity'))
        new_unit = request.form.get('new_unit')
        new_category = request.form.get('new_category')

        new_item = Item(
            name=new_name,
            quantity=new_quantity,
            alert_quantity=new_alert_quantity,
            unit=new_unit, category=new_category
        )
        db.session.add(new_item)

    db.session.commit()

    return redirect(url_for('inventory'))


@app.route('/remove_item/<int:item_id>', methods=['POST'])
def remove_item(item_id):
    print(f"Removing item with ID: {item_id}")
    item = Item.query.get(item_id)
    if item:
        db.session.delete(item)
        db.session.commit()

    return redirect(url_for('inventory'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0')

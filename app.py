

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


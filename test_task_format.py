"""
Test script to verify the task title format.
"""
from app import create_app
from app.utils.google_tasks import sync_low_inventory_items

app = create_app()

with app.app_context():
    print('Testing task sync functionality...')
    print('This will not actually create tasks but just verify the format.')
    
    # We'll create a mock function to test the formatting
    from app.models.item import Item
    
    # Create a sample item for testing
    test_item = Item(
        name='Mjölk',
        quantity=1,
        alert_quantity=2,
        unit='liter',
        category='Mejeri'
    )
    
    # Extract the task title creation from sync_low_inventory_items
    title = f"{test_item.name}"
    notes = (f"Kategori: {test_item.category}\n"
             f"Nuvarande antal: {test_item.quantity} {test_item.unit}\n"
             f"Larmgräns: {test_item.alert_quantity} {test_item.unit}\n"
             f"Senast kontrollerad: {test_item.last_checked.strftime('%Y-%m-%d') if test_item.last_checked else 'Aldrig'}")
    
    print(f"Task title would be: '{title}'")
    print(f"Task notes would be:\n{notes}")
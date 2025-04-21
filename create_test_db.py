"""
Create a test database with sample data.
This script populates the database with sample inventory items.
"""
from app import create_app, db
from app.models.item import Item
from datetime import datetime, timedelta
import random

# Kategorier och artiklar för testdatabasen
test_data = {
    "Mat": [
        {"name": "Kaffe", "quantity": 2, "alert_quantity": 1, "unit": "paket"},
        {"name": "Pasta", "quantity": 5, "alert_quantity": 2, "unit": "paket"},
        {"name": "Ris", "quantity": 1, "alert_quantity": 1, "unit": "kg"},
        {"name": "Konserverade tomater", "quantity": 4, "alert_quantity": 2, "unit": "burkar"},
        {"name": "Olivolja", "quantity": 1, "alert_quantity": 1, "unit": "flaska"},
    ],
    "Förbrukningsmaterial": [
        {"name": "Tvål", "quantity": 3, "alert_quantity": 2, "unit": "st"},
        {"name": "Toalettpapper", "quantity": 8, "alert_quantity": 4, "unit": "rullar"},
        {"name": "Hushållspapper", "quantity": 2, "alert_quantity": 1, "unit": "rullar"},
        {"name": "Diskmedel", "quantity": 1, "alert_quantity": 1, "unit": "flaska"},
    ],
    "Verktyg": [
        {"name": "Spik 50mm", "quantity": 125, "alert_quantity": 20, "unit": "st"},
        {"name": "Träskruv 30mm", "quantity": 42, "alert_quantity": 10, "unit": "st"},
        {"name": "Borrspetsar", "quantity": 5, "alert_quantity": 2, "unit": "set"},
        {"name": "Sandpapper", "quantity": 3, "alert_quantity": 2, "unit": "ark"},
        {"name": "Slippapper", "quantity": 0, "alert_quantity": 5, "unit": "ark"},
        {"name": "Tejp", "quantity": 1, "alert_quantity": 1, "unit": "rulle"},
    ],
    "Elektronik": [
        {"name": "USB-C kablar", "quantity": 2, "alert_quantity": 1, "unit": "st"},
        {"name": "HDMI kablar", "quantity": 1, "alert_quantity": 1, "unit": "st"},
        {"name": "Batterier AA", "quantity": 6, "alert_quantity": 4, "unit": "st"},
        {"name": "Batterier AAA", "quantity": 0, "alert_quantity": 4, "unit": "st"},
    ],
    "Dryck": [
        {"name": "Whiskey Highland Park", "quantity": 1, "alert_quantity": 1, "unit": "flaska"},
        {"name": "Rödvin", "quantity": 3, "alert_quantity": 2, "unit": "flaskor"},
        {"name": "Mineralvatten", "quantity": 5, "alert_quantity": 3, "unit": "flaskor"},
    ]
}

def create_test_database():
    """
    Create a test database with sample data.
    """
    app = create_app()
    
    with app.app_context():
        # Radera befintlig databas och skapa en ny
        db.drop_all()
        db.create_all()
        
        now = datetime.now()
        
        # Skapa artiklar med varierande datum för senaste kontroll
        for category, items in test_data.items():
            for item_data in items:
                # Slumpa datum inom de senaste 10 dagarna
                days_ago = random.randint(0, 10)
                hours_ago = random.randint(0, 23)
                last_checked = now - timedelta(days=days_ago, hours=hours_ago)
                
                item = Item(
                    name=item_data["name"],
                    category=category,
                    quantity=item_data["quantity"],
                    unit=item_data["unit"],
                    alert_quantity=item_data["alert_quantity"],
                    last_checked=last_checked
                )
                db.session.add(item)
        
        db.session.commit()
        print(f"Testdatabas skapad med {sum(len(items) for items in test_data.values())} artiklar i {len(test_data)} kategorier.")

if __name__ == "__main__":
    create_test_database()
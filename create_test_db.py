"""
Create a test database with sample data.
This script populates the database with sample inventory items.
"""
from app import create_app, db
from app.models.item import Item
from datetime import datetime, timedelta
import random
import os
import shutil

# Constants for database paths
INSTANCE_DB_PATH = 'instance/db.sqlite3'

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

def create_test_database(target_path=None):
    """
    Create a test database with sample data.
    
    Args:
        target_path: Optional path where to create the database. 
                    If None, creates in instance/db.sqlite3
    """
    # Determine database URI based on target path
    if target_path is None:
        target_path = INSTANCE_DB_PATH
        db_uri = 'sqlite:///../instance/db.sqlite3'
    else:
        # Make relative path to absolute path
        abs_path = os.path.abspath(target_path)
        db_uri = f'sqlite:///{abs_path}'
    
    print(f"Creating test database at: {target_path}")
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    # Initialize app with the correct database URI
    app = create_app({
        'SQLALCHEMY_DATABASE_URI': db_uri
    })
    
    with app.app_context():
        # Drop existing database and create a new one
        db.drop_all()
        db.create_all()
        
        now = datetime.now()
        
        # Create items with varying dates for last check
        for category, items in test_data.items():
            for item_data in items:
                # Randomize date within the last 10 days
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
        print(f"Test database created with {sum(len(items) for items in test_data.values())} items in {len(test_data)} categories.")
    
    # We no longer save copies to the test directory because we're using .gitignore
    # This ensures we don't commit database files to the repository
    print("Database created successfully - ready for use")

def create_empty_database(target_path=None):
    """
    Create an empty database with schema but no data.
    
    Args:
        target_path: Optional path where to create the database.
                    If None, creates in instance/db.sqlite3
    """
    # Determine database URI based on target path
    if target_path is None:
        target_path = INSTANCE_DB_PATH
        db_uri = 'sqlite:///../instance/db.sqlite3'
    else:
        # Make relative path to absolute path
        abs_path = os.path.abspath(target_path)
        db_uri = f'sqlite:///{abs_path}'
    
    print(f"Creating empty database at: {target_path}")
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    # Initialize app with the correct database URI
    app = create_app({
        'SQLALCHEMY_DATABASE_URI': db_uri
    })
    
    with app.app_context():
        # Drop existing database and create a new one
        db.drop_all()
        db.create_all()
        print(f"Empty database created at {target_path}")
    
    # We no longer save copies to the test directory because we're using .gitignore
    # This ensures we don't commit database files to the repository
    print("Empty database created successfully - ready for use")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Create databases for the inventera application')
    parser.add_argument('--empty', action='store_true', help='Create an empty database')
    parser.add_argument('--path', type=str, help='Custom path for the database')
    args = parser.parse_args()
    
    if args.empty:
        create_empty_database(args.path)
    else:
        create_test_database(args.path)
#!/usr/bin/env python3
"""
Database migration script for Inventera.
Updates the database schema for the Google Tasks integration.
"""
import os
import sys
import sqlite3
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('migrate_db')

def get_db_path():
    """Get the path to the database file."""
    # Check for instance/db.sqlite3 first
    instance_db = os.path.join('instance', 'db.sqlite3')
    if os.path.exists(instance_db):
        return instance_db
    
    # Check for db.sqlite3 in current directory
    if os.path.exists('db.sqlite3'):
        return 'db.sqlite3'
    
    # Check for test database
    test_db = os.path.join('tests', 'data', 'test_db.sqlite3')
    if os.path.exists(test_db):
        return test_db
    
    return None

def migrate_database(db_path):
    """
    Perform database migration to update schema.
    
    Args:
        db_path: Path to SQLite database file
    """
    logger.info(f"Starting migration for database: {db_path}")
    
    try:
        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if 'item' table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='item'")
        if not cursor.fetchone():
            logger.error("Item table not found in database")
            return False
        
        # Check if the necessary columns already exist
        cursor.execute("PRAGMA table_info(item)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Add task_id column if it doesn't exist
        if 'task_id' not in columns:
            logger.info("Adding 'task_id' column to 'item' table")
            cursor.execute("ALTER TABLE item ADD COLUMN task_id TEXT")
        else:
            logger.info("Column 'task_id' already exists")
        
        # Add added_to_task column if it doesn't exist
        if 'added_to_task' not in columns:
            logger.info("Adding 'added_to_task' column to 'item' table")
            cursor.execute("ALTER TABLE item ADD COLUMN added_to_task TIMESTAMP")
        else:
            logger.info("Column 'added_to_task' already exists")
        
        # Create settings table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            value TEXT
        )
        """)
        logger.info("Created 'settings' table if it didn't exist")
        
        # Create category_task_mapping table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS category_task_mapping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL UNIQUE,
            tasklist_id TEXT NOT NULL,
            tasklist_name TEXT NOT NULL
        )
        """)
        logger.info("Created 'category_task_mapping' table if it didn't exist")
        
        # Commit the changes
        conn.commit()
        logger.info("Migration completed successfully")
        
        return True
    
    except sqlite3.Error as e:
        logger.error(f"SQLite error: {e}")
        return False
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False
    
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    # Get the database path
    db_path = get_db_path()
    
    if not db_path:
        logger.error("No database file found")
        sys.exit(1)
    
    # Perform the migration
    success = migrate_database(db_path)
    
    if success:
        logger.info("Database migration completed successfully")
        sys.exit(0)
    else:
        logger.error("Database migration failed")
        sys.exit(1)
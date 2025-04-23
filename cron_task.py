#!/usr/bin/env python3
"""
Cron script for inventory tasks:
1. Synchronize low inventory items to Google Tasks
2. Check for items that haven't been checked in over 7 days

This script is designed to be run daily via a cron job.

Example crontab entry (run daily at midnight):
0 0 * * * cd /path/to/inventera && python3 cron_task.py >> /path/to/inventera/cron.log 2>&1
"""
import os
import sys
import logging
from datetime import datetime
from flask import Flask

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('cron_task')

def create_app():
    """Create a Flask app specifically for cron jobs."""
    from app import create_app as create_flask_app
    
    # Create the Flask app with test_config=None to use production settings
    flask_app = create_flask_app(test_config=None)
    
    return flask_app

def run_tasks():
    """Run all scheduled tasks."""
    logger.info("Starting cron tasks at %s", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    
    # Create app and push context
    app = create_app()
    with app.app_context():
        from app.utils.google_tasks import sync_low_inventory_items, check_old_items
        from app.models.settings import Settings
        
        # Check if Google Tasks integration is enabled
        google_token = Settings.get('google_token')
        if not google_token:
            logger.warning("Google Tasks integration is not configured. Skipping sync.")
        else:
            # 1. Sync low inventory items
            logger.info("Syncing low inventory items to Google Tasks...")
            synced_count, errors = sync_low_inventory_items()
            
            logger.info("Synced %d items to Google Tasks", synced_count)
            if errors:
                logger.error("Errors during sync: %s", "\n".join(errors))
        
        # 2. Check for items that haven't been verified in over 7 days
        logger.info("Checking for old items...")
        old_items = check_old_items()
        
        if old_items:
            logger.warning("Found %d items not checked in over 7 days:", len(old_items))
            for item in old_items:
                days = (datetime.utcnow() - item.last_checked).days if item.last_checked else "Never"
                logger.warning("- %s (Category: %s) - Last checked: %s", 
                             item.name, item.category, days)
        else:
            logger.info("No old items found.")
    
    logger.info("Cron tasks completed at %s", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

if __name__ == '__main__':
    run_tasks()
"""
Google Tasks API utilities for the inventory application.
"""
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from flask import current_app
from app.models.item import Item
from app.models.settings import Settings, CategoryTaskMapping
from app import db

# Import Google API client library
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False


class GoogleTasksService:
    """
    Service for interacting with Google Tasks API.
    """
    # Path to store token (excluded from git)
    TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
                              'instance', 'google_token.json')
    # Scopes needed for Google Tasks API
    SCOPES = ['https://www.googleapis.com/auth/tasks']
    
    def __init__(self):
        """Initialize Google Tasks service."""
        self.service = None
        self.authenticated = False
        self.error_message = ""
        
        # Check if prerequisites are met
        if not GOOGLE_API_AVAILABLE:
            self.error_message = "Google API client libraries not installed. Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            return
        
        # Try to load credentials
        self._load_credentials()
    
    def _load_credentials(self) -> None:
        """Load credentials from token file or settings."""
        try:
            # First try to load from file
            if os.path.exists(self.TOKEN_FILE):
                creds = Credentials.from_authorized_user_info(
                    json.load(open(self.TOKEN_FILE, 'r')),
                    self.SCOPES
                )
            else:
                # Try to load from database
                token_json = Settings.get('google_token')
                if token_json:
                    creds = Credentials.from_authorized_user_info(
                        json.loads(token_json),
                        self.SCOPES
                    )
                else:
                    self.error_message = "No stored credentials found. Please authenticate first."
                    return
            
            # Check if credentials are valid
            if creds and creds.valid:
                self.service = build('tasks', 'v1', credentials=creds)
                self.authenticated = True
            else:
                self.error_message = "Stored credentials are invalid or expired. Please re-authenticate."
        except Exception as e:
            self.error_message = f"Error loading credentials: {str(e)}"
    
    def save_credentials(self, token_info: Dict) -> None:
        """
        Save credentials to both file and database.
        
        Args:
            token_info: The token information to save
        """
        try:
            # Save to file
            os.makedirs(os.path.dirname(self.TOKEN_FILE), exist_ok=True)
            with open(self.TOKEN_FILE, 'w') as token_file:
                json.dump(token_info, token_file)
            
            # Save to database
            Settings.set('google_token', json.dumps(token_info))
            
            # Re-initialize with new credentials
            self._load_credentials()
        except Exception as e:
            current_app.logger.error(f"Error saving credentials: {str(e)}")
            self.error_message = f"Error saving credentials: {str(e)}"
    
    def is_authenticated(self) -> bool:
        """Check if the service is authenticated."""
        return self.authenticated
    
    def get_error(self) -> str:
        """Get the current error message."""
        return self.error_message
    
    def get_tasklists(self) -> List[Dict]:
        """
        Get all available task lists.
        
        Returns:
            List of task list dictionaries with 'id' and 'title' keys
        """
        if not self.authenticated:
            return []
        
        try:
            results = self.service.tasklists().list().execute()
            lists = results.get('items', [])
            return [{'id': task_list['id'], 'title': task_list['title']} for task_list in lists]
        except Exception as e:
            current_app.logger.error(f"Error fetching task lists: {str(e)}")
            self.error_message = f"Error fetching task lists: {str(e)}"
            return []
    
    def add_task(self, title: str, notes: str, tasklist_id: str) -> Optional[str]:
        """
        Add a new task to a task list.
        
        Args:
            title: Task title
            notes: Task notes/description
            tasklist_id: ID of the task list to add to
            
        Returns:
            Task ID if successful, None otherwise
        """
        if not self.authenticated:
            return None
        
        try:
            task = {
                'title': title,
                'notes': notes,
                'status': 'needsAction'
            }
            
            result = self.service.tasks().insert(
                tasklist=tasklist_id,
                body=task
            ).execute()
            
            return result.get('id')
        except Exception as e:
            current_app.logger.error(f"Error adding task: {str(e)}")
            self.error_message = f"Error adding task: {str(e)}"
            return None
    
    def update_task(self, task_id: str, tasklist_id: str, 
                    title: Optional[str] = None, 
                    notes: Optional[str] = None, 
                    status: Optional[str] = None) -> bool:
        """
        Update an existing task.
        
        Args:
            task_id: ID of the task to update
            tasklist_id: ID of the task list containing the task
            title: New title (optional)
            notes: New notes (optional)
            status: New status (optional)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.authenticated:
            return False
        
        try:
            # First get the existing task
            task = self.service.tasks().get(
                tasklist=tasklist_id,
                task=task_id
            ).execute()
            
            # Update fields that were provided
            if title is not None:
                task['title'] = title
            if notes is not None:
                task['notes'] = notes
            if status is not None:
                task['status'] = status
            
            # Update the task
            self.service.tasks().update(
                tasklist=tasklist_id,
                task=task_id,
                body=task
            ).execute()
            
            return True
        except Exception as e:
            current_app.logger.error(f"Error updating task: {str(e)}")
            self.error_message = f"Error updating task: {str(e)}"
            return False
    
    def get_tasks(self, tasklist_id: str) -> List[Dict]:
        """
        Get all tasks in a task list.
        
        Args:
            tasklist_id: ID of the task list
            
        Returns:
            List of task dictionaries
        """
        if not self.authenticated:
            return []
        
        try:
            results = self.service.tasks().list(tasklist=tasklist_id).execute()
            return results.get('items', [])
        except Exception as e:
            current_app.logger.error(f"Error fetching tasks: {str(e)}")
            self.error_message = f"Error fetching tasks: {str(e)}"
            return []


def sync_low_inventory_items() -> Tuple[int, List[str]]:
    """
    Sync inventory items that are below alert threshold to Google Tasks.
    
    Returns:
        Tuple with count of synced items and list of error messages
    """
    # Initialize variables
    synced_items = 0
    errors = []
    
    # Get tasks service
    tasks_service = GoogleTasksService()
    
    # Check if authenticated
    if not tasks_service.is_authenticated():
        errors.append(f"Google Tasks not authenticated: {tasks_service.get_error()}")
        return synced_items, errors
    
    # Get default task list
    default_tasklist = CategoryTaskMapping.get_default_tasklist()
    if not default_tasklist:
        errors.append("No default task list configured.")
        return synced_items, errors
    
    # Get items below alert threshold
    try:
        items_to_sync = Item.query.filter(
            Item.quantity <= Item.alert_quantity
        ).all()
        
        current_app.logger.info(f"Found {len(items_to_sync)} items below alert threshold.")
        
        for item in items_to_sync:
            try:
                # Skip if already in tasks and last_checked is after added_to_task
                if (item.task_id and item.added_to_task and item.last_checked and 
                        item.last_checked <= item.added_to_task):
                    continue
                
                # Get appropriate task list for this category
                mapping = CategoryTaskMapping.get_mapping_for_category(item.category)
                
                if mapping:
                    tasklist_id = mapping.tasklist_id
                    tasklist_name = mapping.tasklist_name
                else:
                    # Use default task list
                    tasklist_id = default_tasklist['tasklist_id']
                    tasklist_name = default_tasklist['tasklist_name']
                
                # Create task title and notes
                title = f"Köp {item.name}"
                notes = (f"Kategori: {item.category}\n"
                         f"Nuvarande antal: {item.quantity} {item.unit}\n"
                         f"Larmgräns: {item.alert_quantity} {item.unit}\n"
                         f"Senast kontrollerad: {item.last_checked.strftime('%Y-%m-%d') if item.last_checked else 'Aldrig'}")
                
                # If already has a task_id, update the existing task
                if item.task_id:
                    success = tasks_service.update_task(
                        task_id=item.task_id,
                        tasklist_id=tasklist_id,
                        title=title,
                        notes=notes
                    )
                    if success:
                        item.added_to_task = datetime.utcnow()
                        synced_items += 1
                    else:
                        # If update fails, try creating a new task
                        item.task_id = None
                
                # If no task_id or update failed, create a new task
                if not item.task_id:
                    task_id = tasks_service.add_task(
                        title=title,
                        notes=notes,
                        tasklist_id=tasklist_id
                    )
                    
                    if task_id:
                        item.task_id = task_id
                        item.added_to_task = datetime.utcnow()
                        synced_items += 1
                    else:
                        errors.append(f"Failed to create task for {item.name}: {tasks_service.get_error()}")
            
            except Exception as e:
                current_app.logger.error(f"Error syncing item {item.name}: {str(e)}")
                errors.append(f"Error syncing {item.name}: {str(e)}")
        
        # Commit all changes
        db.session.commit()
        
    except Exception as e:
        current_app.logger.error(f"Error in sync_low_inventory_items: {str(e)}")
        errors.append(f"General error: {str(e)}")
    
    return synced_items, errors


def check_old_items() -> List[Item]:
    """
    Check for items that haven't been checked in over 7 days.
    
    Returns:
        List of items that need attention
    """
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    
    try:
        old_items = Item.query.filter(
            (Item.last_checked <= seven_days_ago) | 
            (Item.last_checked == None)
        ).all()
        
        return old_items
    except Exception as e:
        current_app.logger.error(f"Error checking old items: {str(e)}")
        return []
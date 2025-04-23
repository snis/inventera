"""
Google Tasks API utilities for the inventory application using API key authentication.
"""
import os
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from flask import current_app
from app.models.item import Item
from app.models.settings import Settings, CategoryTaskMapping
from app import db

# Base URL for Google Tasks API
API_BASE_URL = "https://tasks.googleapis.com/tasks/v1"

class SimpleGoogleTasksService:
    """
    Simple service for interacting with Google Tasks API.
    This implementation uses API and access tokens for authentication.
    """
    def __init__(self):
        """Initialize Google Tasks service."""
        self.api_key = None
        self.access_token = None
        self.authenticated = False
        self.error_message = ""
        
        # Try to load credentials
        self._load_credentials()
    
    def _load_credentials(self) -> None:
        """Load API key and access token from settings."""
        try:
            # Load API key from database
            self.api_key = Settings.get('google_api_key')
            # Load access token from database
            self.access_token = Settings.get('google_access_token')
            
            if self.api_key and self.access_token:
                self.authenticated = True
            else:
                self.error_message = "Missing API key or access token. Please set both."
        except Exception as e:
            self.error_message = f"Error loading credentials: {str(e)}"
    
    def save_credentials(self, api_key: str, access_token: str) -> None:
        """
        Save API key and access token to database.
        
        Args:
            api_key: The API key to save
            access_token: The access token to save
        """
        try:
            # Save to database
            Settings.set('google_api_key', api_key)
            Settings.set('google_access_token', access_token)
            
            # Re-initialize with new credentials
            self._load_credentials()
        except Exception as e:
            current_app.logger.error(f"Error saving credentials: {str(e)}")
            self.error_message = f"Error saving credentials: {str(e)}"
    
    def remove_credentials(self) -> None:
        """Remove API key and access token from database."""
        try:
            Settings.set('google_api_key', None)
            Settings.set('google_access_token', None)
            self.api_key = None
            self.access_token = None
            self.authenticated = False
        except Exception as e:
            current_app.logger.error(f"Error removing credentials: {str(e)}")
            self.error_message = f"Error removing credentials: {str(e)}"
    
    def is_authenticated(self) -> bool:
        """Check if the service has credentials."""
        return self.authenticated
    
    def get_error(self) -> str:
        """Get the current error message."""
        return self.error_message
    
    def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Optional[Dict]:
        """
        Make an authenticated request to the Tasks API.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (without base URL)
            data: Request data (for POST/PUT)
            
        Returns:
            Response JSON or None if error
        """
        if not self.authenticated:
            return None
        
        url = f"{API_BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        # Add API key to the URL if provided
        if self.api_key:
            url += f"?key={self.api_key}"
        
        try:
            if method == "GET":
                response = requests.get(url, headers=headers)
            elif method == "POST":
                response = requests.post(url, json=data, headers=headers)
            elif method == "PUT":
                response = requests.put(url, json=data, headers=headers)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers)
            else:
                self.error_message = f"Invalid request method: {method}"
                return None
            
            # Debug information
            current_app.logger.debug(f"Request to {url}")
            current_app.logger.debug(f"Response status: {response.status_code}")
            
            # Check for token expiration (status code 401)
            if response.status_code == 401:
                self.error_message = "Access token has expired. Please generate a new token."
                current_app.logger.error("Access token has expired")
                return None
                
            response.raise_for_status()  # Raise exception for HTTP errors
            
            # Return JSON response or empty dict if no content
            return response.json() if response.content else {}
            
        except requests.exceptions.RequestException as e:
            self.error_message = f"API request error: {str(e)}"
            current_app.logger.error(f"API request error: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                current_app.logger.error(f"Response status: {e.response.status_code}")
                current_app.logger.error(f"Response text: {e.response.text}")
            return None
    
    def get_tasklists(self) -> List[Dict]:
        """
        Get all available task lists.
        
        Returns:
            List of task list dictionaries with 'id' and 'title' keys
        """
        if not self.authenticated:
            return []
        
        try:
            response = self._make_request("GET", "/users/@me/lists")
            if not response:
                return []
            
            lists = response.get('items', [])
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
            task_data = {
                'title': title,
                'notes': notes,
                'status': 'needsAction'
            }
            
            response = self._make_request("POST", f"/lists/{tasklist_id}/tasks", task_data)
            if not response:
                return None
            
            return response.get('id')
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
            existing_task = self._make_request("GET", f"/lists/{tasklist_id}/tasks/{task_id}")
            if not existing_task:
                return False
            
            # Update fields that were provided
            update_data = {}
            if title is not None:
                update_data['title'] = title
            if notes is not None:
                update_data['notes'] = notes
            if status is not None:
                update_data['status'] = status
            
            # Merge with existing task data
            task_data = {**existing_task, **update_data}
            
            # Update the task
            response = self._make_request("PUT", f"/lists/{tasklist_id}/tasks/{task_id}", task_data)
            return response is not None
            
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
            response = self._make_request("GET", f"/lists/{tasklist_id}/tasks")
            if not response:
                return []
            
            return response.get('items', [])
        except Exception as e:
            current_app.logger.error(f"Error fetching tasks: {str(e)}")
            self.error_message = f"Error fetching tasks: {str(e)}"
            return []


# For backward compatibility, use the same class name
GoogleTasksService = SimpleGoogleTasksService


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
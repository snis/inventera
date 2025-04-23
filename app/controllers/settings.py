"""
Settings blueprint for the inventory application.
Contains routes for application settings management.
"""
from flask import Blueprint, request, jsonify, redirect, url_for, current_app, render_template
from typing import Dict, List
import json
import os

from app import db
from app.models.settings import Settings, CategoryTaskMapping
from app.utils.responses import create_response, is_ajax_request
from app.utils.google_tasks import GoogleTasksService, sync_low_inventory_items, check_old_items

# Create blueprint
settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/settings')
def settings():
    """
    Render the settings page.
    
    Returns:
        Rendered settings template
    """
    try:
        # Get Google Tasks service
        tasks_service = GoogleTasksService()
        
        # Get all task list mappings
        mappings = CategoryTaskMapping.query.all()
        
        # Get default task list
        default_tasklist = CategoryTaskMapping.get_default_tasklist()
        
        # Get all task lists if authenticated
        tasklists = []
        if tasks_service.is_authenticated():
            tasklists = tasks_service.get_tasklists()
        
        # Get all unique categories from mappings for display
        categories = db.session.query(db.distinct(CategoryTaskMapping.category)).all()
        categories = [c[0] for c in categories]
        
        return render_template(
            'settings.html',
            authenticated=tasks_service.is_authenticated(),
            error_message=tasks_service.get_error(),
            mappings=mappings,
            default_tasklist=default_tasklist,
            tasklists=tasklists,
            categories=categories
        )
    except Exception as e:
        current_app.logger.error(f"Error rendering settings page: {str(e)}")
        return render_template('error.html', message="Ett fel uppstod vid hämtning av inställningar.")


@settings_bp.route('/settings/api_key', methods=['POST'])
def set_api_key():
    """
    Set Google Tasks API key.
    
    Returns:
        JSON response or redirect
    """
    try:
        # Get API key from request
        api_key = request.form.get('api_key')
        
        if not api_key:
            return create_response(
                success=False,
                message='Ingen API-nyckel angiven',
                redirect_url=url_for('settings.settings')
            )
        
        # Save the API key
        tasks_service = GoogleTasksService()
        tasks_service.save_api_key(api_key)
        
        if tasks_service.is_authenticated():
            return create_response(
                success=True,
                message='API-nyckel sparad',
                redirect_url=url_for('settings.settings')
            )
        else:
            return create_response(
                success=False,
                message=f'Misslyckades med att spara API-nyckel: {tasks_service.get_error()}',
                redirect_url=url_for('settings.settings')
            )
    
    except Exception as e:
        current_app.logger.error(f"Error in set_api_key: {str(e)}")
        return create_response(
            success=False,
            message='Ett fel uppstod vid sparande av API-nyckel',
            redirect_url=url_for('settings.settings')
        )


@settings_bp.route('/settings/mapping', methods=['POST'])
def update_mapping():
    """
    Update category to task list mapping.
    
    Returns:
        JSON response or redirect
    """
    try:
        category = request.form.get('category')
        tasklist_id = request.form.get('tasklist_id')
        tasklist_name = request.form.get('tasklist_name')
        
        if not category or not tasklist_id or not tasklist_name:
            return create_response(
                success=False,
                message='Alla fält måste anges',
                redirect_url=url_for('settings.settings')
            )
        
        # Check if mapping already exists
        mapping = CategoryTaskMapping.query.filter_by(category=category).first()
        
        if mapping:
            mapping.tasklist_id = tasklist_id
            mapping.tasklist_name = tasklist_name
        else:
            mapping = CategoryTaskMapping(
                category=category,
                tasklist_id=tasklist_id,
                tasklist_name=tasklist_name
            )
            db.session.add(mapping)
        
        db.session.commit()
        
        return create_response(
            success=True,
            message=f'Mappning för {category} uppdaterad',
            redirect_url=url_for('settings.settings')
        )
    
    except Exception as e:
        current_app.logger.error(f"Error updating mapping: {str(e)}")
        return create_response(
            success=False,
            message='Ett fel uppstod vid uppdatering av mappning',
            redirect_url=url_for('settings.settings')
        )


@settings_bp.route('/settings/default', methods=['POST'])
def set_default():
    """
    Set default task list.
    
    Returns:
        JSON response or redirect
    """
    try:
        tasklist_id = request.form.get('tasklist_id')
        tasklist_name = request.form.get('tasklist_name')
        
        if not tasklist_id or not tasklist_name:
            return create_response(
                success=False,
                message='Alla fält måste anges',
                redirect_url=url_for('settings.settings')
            )
        
        # Set default task list
        CategoryTaskMapping.set_default_tasklist(tasklist_id, tasklist_name)
        
        return create_response(
            success=True,
            message='Standarduppgiftslista uppdaterad',
            redirect_url=url_for('settings.settings')
        )
    
    except Exception as e:
        current_app.logger.error(f"Error setting default task list: {str(e)}")
        return create_response(
            success=False,
            message='Ett fel uppstod vid uppdatering av standarduppgiftslista',
            redirect_url=url_for('settings.settings')
        )


@settings_bp.route('/settings/delete_mapping/<int:mapping_id>', methods=['POST'])
def delete_mapping(mapping_id):
    """
    Delete a category to task list mapping.
    
    Args:
        mapping_id: ID of the mapping to delete
        
    Returns:
        JSON response or redirect
    """
    try:
        mapping = CategoryTaskMapping.query.get(mapping_id)
        
        if mapping:
            category = mapping.category
            db.session.delete(mapping)
            db.session.commit()
            
            return create_response(
                success=True,
                message=f'Mappning för {category} borttagen',
                redirect_url=url_for('settings.settings')
            )
        else:
            return create_response(
                success=False,
                message='Mappning hittades inte',
                redirect_url=url_for('settings.settings')
            )
    
    except Exception as e:
        current_app.logger.error(f"Error deleting mapping: {str(e)}")
        return create_response(
            success=False,
            message='Ett fel uppstod vid borttagning av mappning',
            redirect_url=url_for('settings.settings')
        )


@settings_bp.route('/sync_tasks', methods=['POST'])
def sync_tasks():
    """
    Sync low inventory items to Google Tasks.
    
    Returns:
        JSON response for AJAX requests, redirect to index for non-AJAX requests
    """
    try:
        synced_count, errors = sync_low_inventory_items()
        
        if errors:
            error_message = "\n".join(errors)
            current_app.logger.error(f"Errors during sync: {error_message}")
            
            if is_ajax_request():
                return jsonify({
                    'status': 'partial',
                    'message': f'Synkade {synced_count} artiklar med fel: {error_message}'
                })
            else:
                return redirect(url_for('main.index'))
        
        if is_ajax_request():
            return jsonify({
                'status': 'success',
                'message': f'Synkade {synced_count} artiklar till Google Tasks'
            })
        else:
            return redirect(url_for('main.index'))
    
    except Exception as e:
        current_app.logger.error(f"Error in sync_tasks: {str(e)}")
        return create_response(
            success=False,
            message='Ett fel uppstod vid synkronisering',
            redirect_url=url_for('main.index')
        )
"""
Settings blueprint for the inventory application.
Contains routes for application settings management.
"""
from flask import Blueprint, request, jsonify, redirect, url_for, current_app, render_template, session
from typing import Dict, List
import json
import os
import secrets

from app import db
from app.models.settings import Settings, CategoryTaskMapping
from app.utils.responses import create_response, is_ajax_request
from app.utils.google_tasks import GoogleTasksService, sync_low_inventory_items, check_old_items
from app.utils.google_oauth import GoogleOAuth

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
        
        # Get OAuth status
        oauth = GoogleOAuth()
        client_configured = oauth.is_configured()
        has_token = oauth.get_token() is not None
        
        # Get all task lists if authenticated
        tasklists = []
        
        if tasks_service.is_authenticated():
            tasklists = tasks_service.get_tasklists()
            
            # Debug logging for tasklists
            current_app.logger.debug(f"Retrieved {len(tasklists)} task lists")
            for tasklist in tasklists:
                current_app.logger.debug(f"Task list: {tasklist}")
        
        # Get all existing categories from the database
        from app.models.item import Item
        existing_categories = db.session.query(db.distinct(Item.category)).all()
        existing_categories = sorted([c[0] for c in existing_categories])
        
        # Get unique categories from mappings for display
        mapped_categories = db.session.query(db.distinct(CategoryTaskMapping.category)).all()
        mapped_categories = [c[0] for c in mapped_categories]
        
        # Get unmapped categories (categories that don't have a mapping yet)
        unmapped_categories = [c for c in existing_categories if c not in mapped_categories]
        
        return render_template(
            'settings.html',
            authenticated=tasks_service.is_authenticated(),
            error_message=tasks_service.get_error(),
            mappings=mappings,
            default_tasklist=default_tasklist,
            tasklists=tasklists,
            categories=existing_categories,
            unmapped_categories=unmapped_categories,
            client_configured=client_configured,
            has_token=has_token
        )
    except Exception as e:
        current_app.logger.error(f"Error rendering settings page: {str(e)}")
        return render_template('error.html', message="Ett fel uppstod vid hämtning av inställningar.")


@settings_bp.route('/settings/client_credentials', methods=['POST'])
def set_client_credentials():
    """
    Set Google OAuth client credentials.
    
    Returns:
        JSON response or redirect
    """
    try:
        # Get credentials from request
        client_id = request.form.get('client_id')
        client_secret = request.form.get('client_secret')
        
        if not client_id or not client_secret:
            return create_response(
                success=False,
                message='Både Client ID och Client Secret måste anges',
                redirect_url=url_for('settings.settings')
            )
        
        # Save the credentials
        tasks_service = GoogleTasksService()
        tasks_service.save_credentials(client_id, client_secret)
        
        return create_response(
            success=True,
            message='OAuth-uppgifter sparade. Du måste nu autentisera med Google.',
            redirect_url=url_for('settings.settings')
        )
    
    except Exception as e:
        current_app.logger.error(f"Error in set_client_credentials: {str(e)}")
        return create_response(
            success=False,
            message='Ett fel uppstod vid sparande av OAuth-uppgifter',
            redirect_url=url_for('settings.settings')
        )

@settings_bp.route('/auth/google')
def auth_google():
    """
    Initiate OAuth flow with Google.
    
    Returns:
        Redirect to Google's authorization page
    """
    try:
        oauth = GoogleOAuth()
        
        if not oauth.is_configured():
            return create_response(
                success=False,
                message='OAuth-klienten är inte konfigurerad. Ange Client ID och Client Secret först.',
                redirect_url=url_for('settings.settings')
            )
        
        # Generate CSRF token for security
        session['oauth_state'] = secrets.token_hex(16)
        
        # Get authorization URL
        redirect_uri = url_for('settings.auth_callback', _external=True)
        auth_url = oauth.get_authorization_url(redirect_uri)
        
        if not auth_url:
            return create_response(
                success=False,
                message='Kunde inte generera auktoriserings-URL',
                redirect_url=url_for('settings.settings')
            )
        
        # Redirect to Google's authorization page
        return redirect(auth_url)
    
    except Exception as e:
        current_app.logger.error(f"Error in auth_google: {str(e)}")
        return create_response(
            success=False,
            message=f'Ett fel uppstod vid autentisering: {str(e)}',
            redirect_url=url_for('settings.settings')
        )

@settings_bp.route('/auth/callback')
def auth_callback():
    """
    Handle OAuth callback from Google.
    
    Returns:
        Redirect to settings page
    """
    try:
        oauth = GoogleOAuth()
        
        if not oauth.is_configured():
            return create_response(
                success=False,
                message='OAuth-klienten är inte konfigurerad',
                redirect_url=url_for('settings.settings')
            )
        
        # Check for errors
        if 'error' in request.args:
            error = request.args.get('error')
            return create_response(
                success=False,
                message=f'Autentisering avbröts: {error}',
                redirect_url=url_for('settings.settings')
            )
        
        # Get authorization code
        code = request.args.get('code')
        if not code:
            return create_response(
                success=False,
                message='Ingen auktoriseringskod mottagen',
                redirect_url=url_for('settings.settings')
            )
        
        # Exchange code for token
        redirect_uri = url_for('settings.auth_callback', _external=True)
        token_data = oauth.fetch_token(redirect_uri, request.url)
        
        if not token_data:
            return create_response(
                success=False,
                message='Kunde inte hämta åtkomsttoken',
                redirect_url=url_for('settings.settings')
            )
        
        return create_response(
            success=True,
            message='Autentisering lyckades! Du kan nu använda Google Tasks-integrationen.',
            redirect_url=url_for('settings.settings')
        )
    
    except Exception as e:
        current_app.logger.error(f"Error in auth_callback: {str(e)}")
        return create_response(
            success=False,
            message=f'Ett fel uppstod vid autentisering: {str(e)}',
            redirect_url=url_for('settings.settings')
        )

@settings_bp.route('/settings/remove_credentials', methods=['POST'])
def remove_credentials():
    """
    Remove Google Tasks API credentials.
    
    Returns:
        JSON response or redirect
    """
    try:
        # Remove credentials
        tasks_service = GoogleTasksService()
        tasks_service.remove_credentials()
        
        return create_response(
            success=True,
            message='Autentiseringsuppgifter borttagna',
            redirect_url=url_for('settings.settings')
        )
    
    except Exception as e:
        current_app.logger.error(f"Error in remove_credentials: {str(e)}")
        return create_response(
            success=False,
            message='Ett fel uppstod vid borttagning av autentiseringsuppgifter',
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
"""
Settings blueprint for the inventory application.
Handles Home Assistant connection configuration, dynamic store-to-todo mapping,
language selection, and general app settings.
"""
from flask import Blueprint, request, jsonify, redirect, url_for, current_app, render_template, session, make_response
from app.models.settings import Settings
from app.utils.helpers import get_distinct_field_values
from app.utils.ha_todo import (
    HomeAssistantTodoClient,
    get_ha_config,
    get_store_todo_map,
    save_store_todo_map
)
from app.utils.i18n import t, SUPPORTED_LANGUAGES

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/set_language/<lang>')
def set_language(lang: str):
    """Switch active UI language and persist in session and cookie."""
    clean_lang = lang[:2].lower()
    if clean_lang not in SUPPORTED_LANGUAGES:
        clean_lang = 'en'
    session['lang'] = clean_lang
    target = request.referrer or url_for('main.index')
    resp = make_response(redirect(target))
    resp.set_cookie('inventera_lang', clean_lang, max_age=60 * 60 * 24 * 365)
    return resp


@settings_bp.route('/settings')
def settings():
    """Render the administrative settings page."""
    try:
        ha_url, ha_token, is_addon = get_ha_config()
        client = HomeAssistantTodoClient(ha_url, ha_token)

        connected = False
        conn_message = ''
        todo_entities = []

        if client.is_configured():
            connected, conn_message = client.test_connection()
            if connected:
                todo_entities = client.get_todo_entities()

        store_todo_map = get_store_todo_map()
        default_todo_entity = Settings.get('ha_default_todo_entity', '')

        # Collect all stores from Items plus any already in the mapping
        stores = sorted(set(get_distinct_field_values('store')) | set(store_todo_map.keys()))

        return render_template(
            'settings.html',
            is_addon=is_addon,
            ha_url=ha_url,
            has_token=bool(ha_token),
            connected=connected,
            conn_message=conn_message,
            todo_entities=todo_entities,
            stores=stores,
            store_todo_map=store_todo_map,
            default_todo_entity=default_todo_entity,
            saved=request.args.get('saved') == '1'
        )
    except Exception as e:
        current_app.logger.error(f"Error rendering settings page: {str(e)}")
        return render_template('error.html', message=t('common.error_generic'))


@settings_bp.route('/settings/save', methods=['POST'])
def save_settings():
    """Persist Home Assistant connection, store mappings, and general settings."""
    try:
        ha_url = (request.form.get('ha_url') or '').strip().rstrip('/')
        ha_token = (request.form.get('ha_token') or '').strip()
        default_todo = (request.form.get('ha_default_todo_entity') or '').strip()
        calendar_url = (request.form.get('calendar_url') or '').strip()

        if ha_url:
            Settings.set('ha_url', ha_url)
        if ha_token:
            Settings.set('ha_token', ha_token)

        Settings.set('ha_default_todo_entity', default_todo)
        Settings.set('calendar_url', calendar_url)

        # Save dynamic store -> todo.* mappings
        new_map = {}
        for key, value in request.form.items():
            if key.startswith('store_map_'):
                store_name = key[len('store_map_'):]
                if store_name and value.strip():
                    new_map[store_name] = value.strip()
        save_store_todo_map(new_map)

        return redirect(url_for('settings.settings', saved='1'))
    except Exception as e:
        current_app.logger.error(f"Error saving settings: {str(e)}")
        return render_template('error.html', message=t('common.error_generic'))


@settings_bp.route('/settings/test_ha', methods=['POST'])
def test_ha():
    """Test Home Assistant connection and return discovered todo.* entities as JSON."""
    try:
        cfg_url, cfg_token, _ = get_ha_config()
        ha_url = (request.form.get('ha_url') or cfg_url).strip().rstrip('/')
        ha_token = (request.form.get('ha_token') or cfg_token).strip()

        client = HomeAssistantTodoClient(ha_url, ha_token)
        ok, msg = client.test_connection()
        entities = client.get_todo_entities() if ok else []

        return jsonify({
            'status': 'success' if ok else 'error',
            'message': msg,
            'todo_entities': entities
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'todo_entities': []})

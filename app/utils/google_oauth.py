"""
Google OAuth utilities for OAuth 2.0 authentication.
"""
import os
import json
from typing import Dict, Optional, Any
from flask import current_app, redirect, url_for, session, request
from oauthlib.oauth2 import WebApplicationClient
import requests
import logging
from app.models.settings import Settings

# Configure OAuth transport security based on environment
# In production, HTTPS is required for OAuth to work securely
# In development, we allow HTTP for easier local testing

# Only allow insecure transport in development mode
if os.environ.get('FLASK_ENV') == 'development' or os.environ.get('INVENTERA_DEV_MODE') == '1':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    print("WARNING: OAUTHLIB_INSECURE_TRANSPORT is enabled for development")
else:
    # Make sure it's not set in production
    os.environ.pop('OAUTHLIB_INSECURE_TRANSPORT', None)
logging.getLogger('google_oauth').setLevel(logging.DEBUG)

# Google OAuth2 endpoint information
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# File to store token (excluded from git)
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        'instance', 'google_token.json')

class GoogleOAuth:
    """
    Handler for Google OAuth2 authentication flow.
    """
    
    def __init__(self):
        """Initialize OAuth handler."""
        self.client_id = Settings.get('google_client_id')
        self.client_secret = Settings.get('google_client_secret')
        self.client = None
        
        if self.client_id and self.client_secret:
            self.client = WebApplicationClient(self.client_id)

    def is_configured(self) -> bool:
        """Check if OAuth is configured with client credentials."""
        return self.client_id is not None and self.client_secret is not None

    def save_credentials(self, client_id: str, client_secret: str) -> None:
        """
        Save OAuth client credentials.
        
        Args:
            client_id: The OAuth client ID
            client_secret: The OAuth client secret
        """
        Settings.set('google_client_id', client_id)
        Settings.set('google_client_secret', client_secret)
        self.client_id = client_id
        self.client_secret = client_secret
        self.client = WebApplicationClient(client_id)
    
    def remove_credentials(self) -> None:
        """Remove OAuth client credentials."""
        Settings.set('google_client_id', None)
        Settings.set('google_client_secret', None)
        self.client_id = None
        self.client_secret = None
        self.client = None
        
        # Also remove tokens
        if os.path.exists(TOKEN_FILE):
            try:
                os.remove(TOKEN_FILE)
            except Exception as e:
                current_app.logger.error(f"Error removing token file: {str(e)}")
        
        Settings.set('google_access_token', None)
        Settings.set('google_refresh_token', None)
    
    def get_authorization_url(self, redirect_uri: str) -> str:
        """
        Get the authorization URL for the OAuth flow.
        
        Args:
            redirect_uri: The URI to redirect to after authorization
            
        Returns:
            Authorization URL
        """
        if not self.client:
            current_app.logger.error("OAuth client not configured")
            return ""
        
        return self.client.prepare_request_uri(
            GOOGLE_AUTH_URL,
            redirect_uri=redirect_uri,
            scope=["https://www.googleapis.com/auth/tasks"],
            prompt="consent",
        )
    
    def fetch_token(self, redirect_uri: str, authorization_response: str) -> Optional[Dict[str, Any]]:
        """
        Exchange authorization code for tokens.
        
        Args:
            redirect_uri: The redirect URI used in the authorization request
            authorization_response: The full callback URL with code
            
        Returns:
            Dictionary with token information or None on error
        """
        if not self.client:
            current_app.logger.error("OAuth client not configured")
            return None
        
        try:
            # Debug logging
            current_app.logger.debug(f"Authorization response: {authorization_response}")
            current_app.logger.debug(f"Redirect URI: {redirect_uri}")
            
            # Parse authorization code from response
            token_url, headers, body = self.client.prepare_token_request(
                GOOGLE_TOKEN_URL,
                authorization_response=authorization_response,
                redirect_url=redirect_uri,
                client_secret=self.client_secret
            )
            
            # More debug logging
            current_app.logger.debug(f"Token URL: {token_url}")
            current_app.logger.debug(f"Token headers: {headers}")
            current_app.logger.debug(f"Token body: {body}")
            
            # Exchange code for token
            token_response = requests.post(
                token_url,
                headers=headers,
                data=body,
                auth=(self.client_id, self.client_secret),
            )
            
            # Check response
            current_app.logger.debug(f"Token response status: {token_response.status_code}")
            current_app.logger.debug(f"Token response: {token_response.text[:200]}")  # Log first 200 chars only
            
            token_response.raise_for_status()
            
            # Parse and store token
            token_data = token_response.json()
            current_app.logger.debug(f"Got token data with keys: {list(token_data.keys())}")
            self._save_token(token_data)
            
            return token_data
        
        except Exception as e:
            current_app.logger.error(f"Error fetching token: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                current_app.logger.error(f"Response status: {e.response.status_code}")
                current_app.logger.error(f"Response text: {e.response.text}")
            return None
    
    def _save_token(self, token_data: Dict[str, Any]) -> None:
        """
        Save token data to database and file.
        
        Args:
            token_data: Dictionary with token information
        """
        try:
            # Save to file
            os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
            with open(TOKEN_FILE, 'w') as token_file:
                json.dump(token_data, token_file)
            
            # Save key parts to database
            if 'access_token' in token_data:
                Settings.set('google_access_token', token_data['access_token'])
            if 'refresh_token' in token_data:
                Settings.set('google_refresh_token', token_data['refresh_token'])
        
        except Exception as e:
            current_app.logger.error(f"Error saving token: {str(e)}")
    
    def get_token(self) -> Optional[Dict[str, Any]]:
        """
        Get current token data.
        
        Returns:
            Dictionary with token information or None if not available
        """
        # First try to load from file
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                current_app.logger.error(f"Error loading token from file: {str(e)}")
        
        # Fall back to database
        access_token = Settings.get('google_access_token')
        refresh_token = Settings.get('google_refresh_token')
        
        if access_token:
            token_data = {
                'access_token': access_token,
                'token_type': 'Bearer'
            }
            if refresh_token:
                token_data['refresh_token'] = refresh_token
            
            return token_data
        
        return None
    
    def refresh_token(self) -> Optional[Dict[str, Any]]:
        """
        Refresh the access token using the refresh token.
        
        Returns:
            New token data or None on error
        """
        if not self.client:
            current_app.logger.error("OAuth client not configured")
            return None
        
        token_data = self.get_token()
        if not token_data or 'refresh_token' not in token_data:
            current_app.logger.error("No refresh token available")
            return None
        
        try:
            refresh_token = token_data['refresh_token']
            
            # Create token refresh request
            token_url, headers, body = self.client.prepare_refresh_token_request(
                GOOGLE_TOKEN_URL,
                refresh_token=refresh_token,
                client_id=self.client_id,
                client_secret=self.client_secret
            )
            
            # Send refresh request
            token_response = requests.post(
                token_url,
                headers=headers,
                data=body,
                auth=(self.client_id, self.client_secret),
            )
            token_response.raise_for_status()
            
            # Parse and store new token
            new_token = token_response.json()
            
            # Make sure to preserve the refresh token if not returned
            if 'refresh_token' not in new_token:
                new_token['refresh_token'] = refresh_token
            
            self._save_token(new_token)
            return new_token
        
        except Exception as e:
            current_app.logger.error(f"Error refreshing token: {str(e)}")
            return None
    
    def revoke_token(self) -> bool:
        """
        Revoke the current token.
        
        Returns:
            True if successful, False otherwise
        """
        token_data = self.get_token()
        if not token_data or 'access_token' not in token_data:
            current_app.logger.error("No token to revoke")
            return False
        
        try:
            # Create revoke request
            access_token = token_data['access_token']
            revoke_response = requests.post(
                GOOGLE_REVOKE_URL,
                params={'token': access_token},
            )
            revoke_response.raise_for_status()
            
            # Clean up saved tokens
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
            
            Settings.set('google_access_token', None)
            Settings.set('google_refresh_token', None)
            
            return True
        
        except Exception as e:
            current_app.logger.error(f"Error revoking token: {str(e)}")
            return False
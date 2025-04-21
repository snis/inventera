"""
Response utilities for handling API responses.
"""
from flask import jsonify, request, redirect, url_for
from typing import Dict, Any, Tuple, Union


def is_ajax_request() -> bool:
    """
    Check if the current request is an AJAX request.
    
    Returns:
        True if the request is an AJAX request, False otherwise
    """
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def create_response(
    success: bool, 
    message: str, 
    data: Dict[str, Any] = None, 
    redirect_url: str = None
) -> Union[Tuple[Dict[str, Any], int], Any]:
    """
    Create a standardized response for API endpoints.
    
    Args:
        success: Whether the operation was successful
        message: Message to return to the client
        data: Additional data to include in the response
        redirect_url: URL to redirect to for non-AJAX requests
        
    Returns:
        JSON response for AJAX requests, redirect for non-AJAX requests
    """
    if is_ajax_request():
        response = {
            'status': 'success' if success else 'error',
            'message': message
        }
        
        if data:
            response.update(data)
            
        return jsonify(response)
    
    if redirect_url:
        return redirect(redirect_url)
    
    # Default redirect to index if no redirect URL is specified
    return redirect(url_for('main.index'))
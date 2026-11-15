"""Response utilities for handling API and HTML responses consistently."""

from typing import Any

from flask import jsonify, redirect, render_template, request, url_for


def is_ajax_request() -> bool:
    """Return True if the current request is an AJAX request."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def create_response(
    success: bool,
    message: str,
    data: dict[str, Any] | None = None,
    redirect_url: str | None = None,
    status_code: int | None = None,
) -> tuple[Any, int] | Any:
    """
    Create a standardized response with proper HTTP status codes.
    """
    code = status_code if status_code is not None else (200 if success else 400)

    if is_ajax_request():
        response: dict[str, Any] = {
            "status": "success" if success else "error",
            "message": message,
        }
        if data:
            response.update(data)
        return jsonify(response), code

    if not success:
        return render_template("error.html", message=message), code

    if redirect_url:
        return redirect(redirect_url)

    return redirect(url_for("main.index"))

import logging
import secrets
import time
from typing import Any, Dict, List, Optional
from flask import current_app, jsonify, request, session
from markupsafe import escape

logger = logging.getLogger(__name__)

# Simple in-memory rate limiter
_rate_limits: Dict[str, List[float]] = {}


def rate_limit_check(key: str, max_requests: int = 15, window_seconds: int = 60) -> bool:
    """
    Checks if a client has exceeded a request rate limit.
    Args:
        key (str): Unique identifier for the client session or IP.
        max_requests (int): Max allowed requests in the window.
        window_seconds (int): Length of the rolling rate limit window.
    Returns:
        bool: True if rate limit is exceeded, False otherwise.
    """
    now = time.time()
    if key not in _rate_limits:
        _rate_limits[key] = []
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < window_seconds]
    if len(_rate_limits[key]) >= max_requests:
        return True
    _rate_limits[key].append(now)
    return False


def escape_html(text: Optional[str]) -> str:
    """
    Escapes HTML characters from raw user input strings to prevent XSS.
    Args:
        text (str): Raw string.
    Returns:
        str: Escaped HTML string.
    """
    return str(escape(text)) if text else ""


def csrf_protect() -> Any:
    """
    Validates session-based CSRF tokens on all state-changing requests.
    """
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)

    # Skip validation in test suites using Flask config
    if current_app.config.get("TESTING"):
        return

    if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")

        # Fallback check for JSON requests
        if not token and request.is_json:
            try:
                token = request.get_json().get("csrf_token")
            except Exception:
                pass

        if not token or token != session.get("csrf_token"):
            logger.warning(f"CSRF violation blocked on route: {request.path}")
            return (
                jsonify({"error": "Security check failed. CSRF token missing or invalid."}),
                400,
            )


def add_security_headers(response: Any) -> Any:
    """
    Appends standard secure HTTP response headers.
    """
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "script-src 'self' 'unsafe-inline';"
    )
    return response

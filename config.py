import datetime
import os


class Config:
    """
    Configuration class for the FIFA World Cup 2026 Smart Stadium Flask application.
    Centralizes environment-driven settings, session management, and security defaults.
    """

    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "fifa-stadium-ops-secret-key-2026")
    PERMANENT_SESSION_LIFETIME = datetime.timedelta(hours=2)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    TESTING = False

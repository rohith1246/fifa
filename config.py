import datetime
import os


class Config:
    """
    Configuration configuration class for the Smart Stadium Flask application.
    """

    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "fifa-stadium-ops-secret-key-2026")
    PERMANENT_SESSION_LIFETIME = datetime.timedelta(hours=2)
    TESTING = False

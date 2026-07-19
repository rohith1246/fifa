import logging
from flask import Flask
from config import Config
from models import init_db
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.api import api_bp
from services.security import csrf_protect, add_security_headers

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Initialize Flask App
app = Flask(__name__)
app.config.from_object(Config)

# Register request filters and middleware
app.before_request(csrf_protect)
app.after_request(add_security_headers)

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(api_bp)

# Initialize database schema and seeds
try:
    logger.info("Initializing World Cup Smart Stadium database schema...")
    init_db()
    logger.info("Database schema initialized.")
except Exception as e:
    logger.error(f"Error during schema initialization: {e}")

if __name__ == "__main__":
    app.run(debug=True)

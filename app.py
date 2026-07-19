import logging
from flask import Flask
from flask_socketio import SocketIO, emit
from config import Config
from database import SessionLocal
from models import init_db, StadiumGate
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
app.url_map.strict_slashes = False

# Initialize SocketIO with threading async mode
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


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


def broadcast_gate_telemetry() -> None:
    """
    Background task that broadcasts updated stadium gate telemetry to all
    connected clients every 10 seconds over WebSockets.
    """
    while True:
        socketio.sleep(10)
        db = SessionLocal()
        try:
            # Query fresh gate status
            gates = db.query(StadiumGate).order_by(StadiumGate.name).all()
            gate_data = [g.to_dict() for g in gates]
            socketio.emit("gate_update", {"gates": gate_data}, namespace="/stadium")
        except Exception as e:
            logger.error(f"Error broadcasting WebSocket telemetry: {e}")
        finally:
            db.close()


@socketio.on("connect", namespace="/stadium")
def handle_connect() -> None:
    """
    Pushes the current gate telemetry immediately to a client upon successful
    WebSocket connection to the /stadium namespace.
    """
    db = SessionLocal()
    try:
        gates = db.query(StadiumGate).order_by(StadiumGate.name).all()
        emit("gate_update", {"gates": [g.to_dict() for g in gates]})
    except Exception as e:
        logger.error(f"Error sending telemetry on connect: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    socketio.start_background_task(broadcast_gate_telemetry)
    socketio.run(app, debug=True)

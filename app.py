import os
import random
import secrets
import json
import logging
import datetime
import time
import requests
import google.generativeai as genai
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    session,
    redirect,
    url_for,
    flash,
)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from sqlalchemy.orm import joinedload
from database import SessionLocal
from models import User, StadiumGate, StaffAllocation, Incident, ChatLog, init_db
from typing import Any, Dict, List, Optional, Tuple
from markupsafe import escape

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Load env variables
load_dotenv()

# Initialize Flask App
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fifa-stadium-ops-secret-key-2026")
app.permanent_session_lifetime = datetime.timedelta(hours=2)

# Simple in-memory rate limiter
_rate_limits: Dict[str, List[float]] = {}

# In-memory gate telemetry cache (30-second TTL) to reduce redundant DB reads
_gate_cache: Dict[str, Any] = {"data": None, "expires_at": 0.0}


def get_cached_gate_dicts(db: Any) -> List[Dict[str, Any]]:
    """
    Returns cached stadium gate data as serialized dictionaries.
    Caches for 30 seconds to reduce redundant DB reads during high traffic.
    Stores plain dicts (not ORM objects) to prevent SQLAlchemy detached-instance errors
    after the originating session is closed.
    Args:
        db: Active SQLAlchemy database session.
    Returns:
        List[Dict[str, Any]]: Ordered list of gate data dictionaries.
    """
    now = time.time()
    if _gate_cache["data"] is not None and now < _gate_cache["expires_at"]:
        return _gate_cache["data"]  # type: ignore[return-value]
    gates = (
        db.query(StadiumGate)
        .options(joinedload(StadiumGate.allocations))
        .order_by(StadiumGate.name)
        .all()
    )
    # Serialize to dicts immediately so the cache is session-independent
    gate_dicts: List[Dict[str, Any]] = [g.to_dict() for g in gates]
    _gate_cache["data"] = gate_dicts
    _gate_cache["expires_at"] = now + 30.0
    return gate_dicts


def invalidate_gate_cache() -> None:
    """Clears the in-memory gate cache to force a fresh DB read on next request."""
    _gate_cache["data"] = None
    _gate_cache["expires_at"] = 0.0


def rate_limit_check(
    key: str, max_requests: int = 15, window_seconds: int = 60
) -> bool:
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


@app.before_request
def csrf_protect() -> Any:
    """
    Validates session-based CSRF tokens on all state-changing requests.
    """
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)

    # Skip validation in test suites
    if app.config.get("TESTING"):
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
                jsonify(
                    {"error": "Security check failed. CSRF token missing or invalid."}
                ),
                400,
            )


@app.after_request
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


# Initialize Database Baseline
try:
    logger.info("Initializing World Cup Smart Stadium database schema...")
    init_db()
    logger.info("Database schema initialized.")
except Exception as e:
    logger.error(f"Error during schema initialization: {e}")


# Helper for GenAI execution
def run_ai_generation(prompt: str, response_type: str = "text") -> Tuple[str, str]:
    """
    Orchestrates primary Google Gemini API with fallback REST support to Groq.
    Args:
        prompt (str): Text prompt to submit to the AI model.
        response_type (str): Output format specification (text or json).
    Returns:
        Tuple[str, str]: Generated output text and model provider used ("gemini" or "groq").
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")

    # Primary: Gemini API
    if gemini_key and gemini_key != "your_gemini_api_key_here":
        genai.configure(api_key=gemini_key)
        models = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash-latest"]
        for m in models:
            try:
                logger.info(f"Attempting Gemini generation ({m})...")
                model = genai.GenerativeModel(m)
                config = {}
                if response_type == "json":
                    config["response_mime_type"] = "application/json"
                response = model.generate_content(prompt, generation_config=config)
                if response.text:
                    logger.info(f"Gemini {m} succeeded.")
                    return response.text.strip(), "gemini"
            except Exception as e:
                logger.warning(f"Gemini {m} generation failed: {e}")

    # Fallback: Groq REST API (direct REST request to avoid proxy configs)
    if groq_key and groq_key != "your_groq_api_key_here":
        try:
            logger.info(
                "Gemini failed or missing API Key. Shifting to Groq REST fallback..."
            )
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "llama-3.3-70b-specdec",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            }
            if response_type == "json":
                payload["response_format"] = {"type": "json_object"}

            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=20,
            )
            if res.status_code == 200:
                result = res.json()["choices"][0]["message"]["content"].strip()
                logger.info("Groq API fallback succeeded.")
                return result, "groq"
            else:
                logger.error(f"Groq API returned HTTP {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Groq API connection failure: {e}")

    # Offline/Mock Fallback
    logger.warning(
        "No operational AI API keys found. Returning mock template response."
    )
    if response_type == "json":
        return (
            json.dumps(
                {
                    "is_valid": True,
                    "severity": "Medium",
                    "dispatch_notes": "Alert field coordinators. Secure area and investigate immediately.",
                    "message": "Proceed carefully. Safe routes are highlighted.",
                }
            ),
            "offline_mock",
        )
    return (
        "Operations standard procedure: please deploy on-field staff to inspect the reported gate quadrant immediately.",
        "offline_mock",
    )


# ----------------- UI Controllers -----------------


@app.route("/")
def index() -> Any:
    """
    Renders the landing page displaying FIFA World Cup 2026 challenge specs.
    """
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register() -> Any:
    """
    Registers a new system user profile (Fan or operations command staff).
    """
    if request.method == "POST":
        username = escape_html(request.form.get("username", "").strip())
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        role = request.form.get("role", "fan")  # "fan" or "operations"

        if not username or not password or not confirm_password:
            flash("All fields are required.", "danger")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))

        db = SessionLocal()
        try:
            exists = db.query(User).filter(User.username == username).first()
            if exists:
                flash("Username is already taken.", "danger")
                return redirect(url_for("register"))

            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                role=role,
            )
            db.add(user)
            db.commit()

            session.permanent = True
            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role

            flash("Registration successful!", "success")
            return redirect(url_for("dashboard"))
        except Exception as e:
            db.rollback()
            logger.error(f"Error during registration: {e}")
            flash("An error occurred. Please try again.", "danger")
            return redirect(url_for("register"))
        finally:
            db.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    """
    Handles secure profile login credentials check.
    """
    if request.method == "POST":
        username = escape_html(request.form.get("username", "").strip())
        password = request.form.get("password")

        if not username or not password:
            flash("Please enter both username and password.", "danger")
            return redirect(url_for("login"))

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user or not check_password_hash(user.password_hash, password):
                flash("Invalid credentials.", "danger")
                return redirect(url_for("login"))

            session.permanent = True
            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role

            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))
        finally:
            db.close()

    return render_template("login.html")


@app.route("/logout")
def logout() -> Any:
    """
    Destroys session references on logout.
    """
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
def dashboard() -> Any:
    """
    Primary Smart Stadium Dashboard panel.
    Loads real-time gate lists and logged incidents to feed both fan and command views.
    """
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .options(joinedload(User.chats))
            .filter(User.id == session["user_id"])
            .first()
        )
        # Query fresh ORM objects (not cache) for template rendering
        gates = (
            db.query(StadiumGate)
            .options(joinedload(StadiumGate.allocations))
            .order_by(StadiumGate.name)
            .all()
        )
        incidents = (
            db.query(Incident).order_by(Incident.created_at.desc()).limit(50).all()
        )
        chats = (
            db.query(ChatLog)
            .filter(ChatLog.user_id == user.id)
            .order_by(ChatLog.created_at)
            .limit(100)
            .all()
        )
        return render_template(
            "dashboard.html", user=user, gates=gates, incidents=incidents, chats=chats
        )
    finally:
        db.close()


# ----------------- GenAI API Endpoints -----------------


@app.route("/api/chat", methods=["POST"])
def api_chat() -> Any:
    """
    Real-time AI Guest Assistant.
    Provides World Cup stadium directions, transit updates, and gate queues.
    """
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    if rate_limit_check(f"chat_{session.get('user_id')}"):
        return jsonify({"error": "Rate limit exceeded. Please wait a moment."}), 429

    data = request.get_json()
    message = escape_html(data.get("message", "").strip())
    if not message:
        return jsonify({"error": "Message content is empty."}), 400

    db = SessionLocal()
    try:
        # Save user chat log
        user_log = ChatLog(user_id=session["user_id"], sender="user", message=message)
        db.add(user_log)
        db.commit()

        # Use serialized dict cache to minimise redundant DB reads
        gate_dicts = get_cached_gate_dicts(db)
        gate_status = "\n".join(
            [
                f"- {g['name']}: Queue Time: {g['queue_time']} mins, Staff: {g['staff_count']}"
                for g in gate_dicts
            ]
        )

        prompt = (
            f"You are the FIFA World Cup 2026 Smart Stadium Assistant at SoFi/MetLife Stadium.\n"
            f"Here is the real-time stadium gate queue status:\n{gate_status}\n\n"
            f'User\'s Question: "{message}"\n\n'
            f"Answer the user's question with precise, helpful, and polite instructions. If they ask about gates, direct them to the ones with the shortest queue times. Keep answers concise (max 3 sentences)."
        )

        response_text, provider = run_ai_generation(prompt)

        # Save AI reply
        ai_log = ChatLog(
            user_id=session["user_id"], sender="assistant", message=response_text
        )
        db.add(ai_log)
        db.commit()

        return (
            jsonify(
                {
                    "response": response_text,
                    "provider": provider,
                    "chat": ai_log.to_dict(),
                }
            ),
            200,
        )
    except Exception as e:
        logger.error(f"Error during AI Chat: {e}")
        return jsonify({"error": "Failed to generate AI response."}), 500
    finally:
        db.close()


@app.route("/api/incident/report", methods=["POST"])
def report_incident() -> Any:
    """
    Logs a stadium operational incident.
    Uses GenAI to classify the severity (Low/Medium/High) and generate action protocols.
    """
    if "user_id" not in session or session.get("role") != "operations":
        return jsonify({"error": "Unauthorized Command Center access."}), 401

    data = request.get_json()
    title = escape_html(data.get("title", "").strip())
    description = escape_html(data.get("description", "").strip())
    category = escape_html(data.get("category", "facilities").strip())

    if not title or not description:
        return jsonify({"error": "Missing incident title or description."}), 400

    prompt = (
        f"You are a World Cup Stadium Operations Incident Classifier.\n"
        f"Incident Title: '{title}'\n"
        f"Incident Details: '{description}'\n"
        f"Category: '{category}'\n\n"
        f"Classify this incident and return ONLY a raw JSON object with the following fields:\n"
        f"- 'severity': Choose exactly 'Low', 'Medium', or 'High' depending on danger/disruption scale.\n"
        f"- 'dispatch_notes': Provide a 1-sentence tactical response instruction for on-field staff.\n"
        f"JSON output format:\n"
        f"{{\n"
        f'  "severity": "High",\n'
        f'  "dispatch_notes": "Immediate dispatch medical first responders to Gate B; clear exit paths."\n'
        f"}}"
    )

    response_text, provider = run_ai_generation(prompt, response_type="json")
    try:
        res_data = json.loads(response_text)
    except Exception:
        # Safe fallback parsing
        res_data = {
            "severity": "Medium"
            if "leak" in description.lower() or "crowd" in description.lower()
            else "Low",
            "dispatch_notes": "Dispatch maintenance crew to inspect the quadrant immediately.",
        }

    severity = res_data.get("severity", "Low")
    dispatch_notes = res_data.get(
        "dispatch_notes", "Standard inspection protocol active."
    )

    db = SessionLocal()
    try:
        incident = Incident(
            title=title,
            description=description,
            category=category,
            severity=severity,
            status="Pending",
            dispatch_notes=dispatch_notes,
        )
        db.add(incident)
        db.commit()

        return jsonify({"incident": incident.to_dict(), "provider": provider}), 201
    except Exception as e:
        logger.error(f"Error logging incident: {e}")
        db.rollback()
        return jsonify({"error": "Failed to log incident."}), 500
    finally:
        db.close()


@app.route("/api/staff/allocate", methods=["POST"])
def allocate_staff() -> Any:
    """
    Executes on-field staff reallocation from one gate to another.
    Recalculates wait times based on new staff counts (more staff = faster flow).
    """
    if "user_id" not in session or session.get("role") != "operations":
        return jsonify({"error": "Operations access required."}), 401

    data = request.get_json()
    gate_id = data.get("gate_id")
    from_gate = escape_html(data.get("from_gate", "").strip())
    quantity = data.get("quantity")
    reason = escape_html(data.get("reason", "").strip())

    if not gate_id or not from_gate or quantity is None:
        return jsonify({"error": "Missing allocation parameters."}), 400

    try:
        quantity = int(quantity)
        if quantity <= 0:
            raise ValueError()
    except ValueError:
        return jsonify({"error": "Staff quantity must be a positive integer."}), 400

    db = SessionLocal()
    try:
        # Find target gate
        gate = db.query(StadiumGate).filter(StadiumGate.id == gate_id).first()
        if not gate:
            return jsonify({"error": "Target gate not found."}), 404

        # Deduct staff from source gate if it exists in DB to simulate conservation
        source_gate = (
            db.query(StadiumGate).filter(StadiumGate.name == from_gate).first()
        )
        if source_gate:
            if source_gate.staff_count < quantity:
                return (
                    jsonify(
                        {
                            "error": f"Insufficient staff at source {from_gate} (Has: {source_gate.staff_count})."
                        }
                    ),
                    400,
                )
            source_gate.staff_count -= quantity
            # Recalculate source queue time (less staff = slower flow)
            source_gate.queue_time = max(5, source_gate.queue_time + (quantity * 3))

        # Add staff to target gate
        gate.staff_count += quantity
        # Recalculate target queue time (more staff = faster flow)
        gate.queue_time = max(2, gate.queue_time - (quantity * 2))

        # Log allocation event
        allocation = StaffAllocation(
            gate_id=gate.id, from_gate=from_gate, quantity=quantity, reason=reason
        )
        db.add(allocation)
        db.commit()
        invalidate_gate_cache()  # Force fresh telemetry after staff movement

        return (
            jsonify(
                {
                    "allocation": allocation.to_dict(),
                    "target_gate": gate.to_dict(),
                    "source_gate": source_gate.to_dict() if source_gate else None,
                }
            ),
            201,
        )
    except Exception as e:
        logger.error(f"Error reallocating staff: {e}")
        db.rollback()
        return jsonify({"error": "Failed to reallocate staff."}), 500
    finally:
        db.close()


@app.route("/api/operations/optimize", methods=["POST"])
def optimize_operations() -> Any:
    """
    GenAI Optimization Planner.
    Analyzes stadium gate parameters and outputs recommended re-allocations to balance flow.
    """
    if "user_id" not in session or session.get("role") != "operations":
        return jsonify({"error": "Operations access required."}), 401

    db = SessionLocal()
    try:
        # Use serialized dict cache so gate data remains valid after session closes
        gate_dicts = get_cached_gate_dicts(db)
        gate_status = "\n".join(
            [
                f"- ID: {g['id']}, Name: {g['name']}, Staff: {g['staff_count']}, Queue Time: {g['queue_time']} mins"
                for g in gate_dicts
            ]
        )

        prompt = (
            f"You are the FIFA World Cup 2026 Stadium Operations Optimizer.\n"
            f"Here is the current gate congestion profile:\n{gate_status}\n\n"
            f"Suggest optimized staff movements to reduce wait times at highly congested gates (e.g. transfer staff from low wait time gates to high wait time gates).\n"
            f"Return ONLY a raw JSON array of recommendation objects. Each object must contain:\n"
            f"- 'from_gate': Name of source gate to move staff FROM.\n"
            f"- 'to_gate_id': ID of target gate to move staff TO.\n"
            f"- 'quantity': Number of staff members to transfer (1 to 5).\n"
            f"- 'reason': A brief reason.\n"
            f"JSON format:\n"
            f"[\n"
            f"  {{\n"
            f'    "from_gate": "Gate C (West Concourse)",\n'
            f'    "to_gate_id": 2,\n'
            f'    "quantity": 3,\n'
            f'    "reason": "Move 3 staff to South Concourse to resolve 35-minute delay."\n'
            f"  }}\n"
            f"]"
        )

        response_text, provider = run_ai_generation(prompt, response_type="json")
        try:
            recommendations = json.loads(response_text)
        except Exception:
            recommendations = []

        return jsonify({"recommendations": recommendations, "provider": provider}), 200
    except Exception as e:
        logger.error(f"Error optimizing operations: {e}")
        return jsonify({"error": "Failed to generate recommendations."}), 500
    finally:
        db.close()


@app.route("/api/gates/simulate", methods=["POST"])
def simulate_spike() -> Any:
    """
    Simulates a crowd density shift by randomizing gate wait times.
    This lets operators test real-time AI re-allocation.
    """
    if "user_id" not in session or session.get("role") != "operations":
        return jsonify({"error": "Operations access required."}), 401

    db = SessionLocal()
    try:
        gates = db.query(StadiumGate).all()
        for g in gates:
            # Randomly fluctuate wait times (5 to 45 mins) and staff (3 to 15)
            g.queue_time = random.randint(5, 45)
            g.staff_count = random.randint(3, 15)
        db.commit()
        invalidate_gate_cache()  # Bust cache after simulation fluctuates gate data

        return (
            jsonify(
                {
                    "message": "Crowd density shift simulated successfully.",
                    "gates": [g.to_dict() for g in gates],
                }
            ),
            200,
        )
    except Exception as e:
        logger.error(f"Error during simulation: {e}")
        db.rollback()
        return jsonify({"error": "Failed to simulate crowd spike."}), 500
    finally:
        db.close()


if __name__ == "__main__":
    app.run(debug=True)

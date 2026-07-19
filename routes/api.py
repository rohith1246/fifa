import json
import logging
from typing import Any, Dict, List
from flask import Blueprint, jsonify, request, session
from sqlalchemy import func
from database import SessionLocal
from models import ChatLog, Incident, StaffAllocation, StadiumGate
from services.ai_service import get_cached_gate_dicts, invalidate_gate_cache, run_ai_generation
from services.security import escape_html, rate_limit_check

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


@api_bp.route("/api/chat", methods=["POST"])
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
            f"IMPORTANT: Detect the language the user wrote in and ALWAYS respond in that SAME language.\n"
            f"Answer the user's question with precise, helpful, and polite instructions. "
            f"If they ask about gates, direct them to the ones with the shortest queue times. "
            f"If they ask about accessibility, mention Gate D (VIP/North Concourse) has priority lanes. "
            f"Keep answers concise (max 3 sentences)."
        )

        response_text, provider = run_ai_generation(prompt)

        # Save AI reply
        ai_log = ChatLog(user_id=session["user_id"], sender="assistant", message=response_text)
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


@api_bp.route("/api/incident/report", methods=["POST"])
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
    dispatch_notes = res_data.get("dispatch_notes", "Standard inspection protocol active.")

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


@api_bp.route("/api/staff/allocate", methods=["POST"])
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
        source_gate = db.query(StadiumGate).filter(StadiumGate.name == from_gate).first()
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


@api_bp.route("/api/operations/optimize", methods=["POST"])
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
            "Suggest optimized staff movements to reduce wait times at highly congested gates "
            "(e.g. transfer staff from low wait time gates to high wait time gates).\n"
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


@api_bp.route("/api/gates/simulate", methods=["POST"])
def simulate_spike() -> Any:
    """
    Simulates a crowd density shift by randomizing gate wait times.
    This lets operators test real-time AI re-allocation.
    """
    if "user_id" not in session or session.get("role") != "operations":
        return jsonify({"error": "Operations access required."}), 401

    import random

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


@api_bp.route("/api/announce", methods=["POST"])
def generate_announcement() -> Any:
    """
    AI-Powered Stadium Public Address Announcement Generator.
    Operations staff submit a topic and the AI generates a clear, multilingual
    stadium-wide broadcast announcement for fans inside the venue.
    """
    if "user_id" not in session or session.get("role") != "operations":
        return jsonify({"error": "Operations access required."}), 401

    if rate_limit_check(f"announce_{session.get('user_id')}"):
        return jsonify({"error": "Rate limit exceeded. Please wait a moment."}), 429

    data = request.get_json()
    topic = escape_html(data.get("topic", "").strip())
    language = escape_html(data.get("language", "English").strip())

    if not topic:
        return jsonify({"error": "Announcement topic is required."}), 400

    prompt = (
        f"You are the FIFA World Cup 2026 Stadium Public Address System Operator.\n"
        f"Generate a professional, clear, and friendly stadium-wide PA announcement in {language}.\n"
        f"Announcement Topic: '{topic}'\n\n"
        f"Guidelines:\n"
        f"- Keep it under 60 words.\n"
        f"- Use a warm, authoritative, and calm tone suitable for a large crowd.\n"
        f"- Begin with 'Attention all fans' or equivalent in the target language.\n"
        f"- If the topic is safety-related, use an urgent but composed tone.\n"
        f"Output ONLY the final announcement text. No labels or preamble."
    )

    try:
        announcement_text, provider = run_ai_generation(prompt)
        return (
            jsonify(
                {
                    "announcement": announcement_text,
                    "language": language,
                    "topic": topic,
                    "provider": provider,
                }
            ),
            200,
        )
    except Exception as e:
        logger.error(f"Error generating announcement: {e}")
        return jsonify({"error": "Failed to generate announcement."}), 500


@api_bp.route("/api/matchday", methods=["GET"])
def matchday_context() -> Any:
    """
    Returns FIFA World Cup 2026 tournament matchday context.
    Provides real-time fixture metadata, venue details, and AI-generated
    fan preparation tips for the current matchday.
    """
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    # FIFA World Cup 2026 venue and fixture context
    venues: List[Dict[str, Any]] = [
        {
            "id": 1,
            "name": "MetLife Stadium",
            "city": "East Rutherford, NJ",
            "capacity": 82500,
            "country": "USA",
        },
        {
            "id": 2,
            "name": "SoFi Stadium",
            "city": "Inglewood, CA",
            "capacity": 70240,
            "country": "USA",
        },
        {
            "id": 3,
            "name": "AT&T Stadium",
            "city": "Arlington, TX",
            "capacity": 80000,
            "country": "USA",
        },
        {
            "id": 4,
            "name": "Estadio Azteca",
            "city": "Mexico City",
            "capacity": 87500,
            "country": "Mexico",
        },
        {"id": 5, "name": "BC Place", "city": "Vancouver", "capacity": 54500, "country": "Canada"},
    ]

    prompt = (
        "You are the FIFA World Cup 2026 Operations Intelligence System.\n"
        "Generate a concise matchday briefing for stadium operations teams covering:\n"
        "1. Crowd management tip for a full stadium (80,000+ fans).\n"
        "2. One key transport or gate recommendation for today's fixture.\n"
        "3. A fan morale message to display on stadium screens.\n"
        "Keep the total response under 80 words. Use a professional operations tone."
    )

    try:
        briefing, provider = run_ai_generation(prompt)
        return (
            jsonify(
                {
                    "venues": venues,
                    "total_matches": 104,
                    "host_countries": ["USA", "Canada", "Mexico"],
                    "tournament_dates": "June 11 – July 19, 2026",
                    "operations_briefing": briefing,
                    "provider": provider,
                }
            ),
            200,
        )
    except Exception as e:
        logger.error(f"Error fetching matchday context: {e}")
        return jsonify({"error": "Failed to load matchday context."}), 500


@api_bp.route("/api/health", methods=["GET"])
def health_check() -> Any:
    """
    System health check endpoint for monitoring and uptime verification.
    Returns operational status and database connectivity state.
    """
    db = SessionLocal()
    try:
        gate_count = db.query(StadiumGate).count()
        return jsonify({
            "status": "healthy",
            "service": "FIFA World Cup 2026 Smart Stadium Platform",
            "database": "connected",
            "gates_configured": gate_count,
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"status": "degraded", "error": str(e)}), 503
    finally:
        db.close()


@api_bp.route("/api/analytics/summary", methods=["GET"])
def analytics_summary() -> Any:
    """
    Stadium Operations Analytics Summary.
    Provides aggregate KPIs for tournament decision-making: total incidents,
    average gate wait times, total staff deployed, and fan chat interactions.
    """
    if "user_id" not in session or session.get("role") != "operations":
        return jsonify({"error": "Operations access required."}), 401

    db = SessionLocal()
    try:
        total_incidents = db.query(Incident).count()
        high_severity = db.query(Incident).filter(Incident.severity == "High").count()
        pending_incidents = db.query(Incident).filter(Incident.status == "Pending").count()

        avg_queue = db.query(func.avg(StadiumGate.queue_time)).scalar() or 0
        total_staff = db.query(func.sum(StadiumGate.staff_count)).scalar() or 0
        total_capacity = db.query(func.sum(StadiumGate.capacity)).scalar() or 0

        total_chats = db.query(ChatLog).count()
        total_reallocations = db.query(StaffAllocation).count()

        return jsonify({
            "kpis": {
                "total_incidents": total_incidents,
                "high_severity_incidents": high_severity,
                "pending_incidents": pending_incidents,
                "average_queue_time_mins": round(float(avg_queue), 1),
                "total_staff_deployed": int(total_staff),
                "total_gate_capacity": int(total_capacity),
                "total_fan_interactions": total_chats,
                "total_staff_reallocations": total_reallocations,
            }
        }), 200
    except Exception as e:
        logger.error(f"Error fetching analytics: {e}")
        return jsonify({"error": "Failed to load analytics."}), 500
    finally:
        db.close()


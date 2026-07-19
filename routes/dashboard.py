from typing import Any
from flask import Blueprint, redirect, render_template, session, url_for
from sqlalchemy.orm import joinedload
from database import SessionLocal
from models import ChatLog, Incident, StadiumGate, User

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index() -> Any:
    """
    Renders the landing page displaying FIFA World Cup 2026 challenge specs.
    """
    if "user_id" in session:
        return redirect(url_for("dashboard.dashboard"))
    return render_template("index.html")


@dashboard_bp.route("/dashboard")
def dashboard() -> Any:
    """
    Primary Smart Stadium Dashboard panel.
    Loads real-time gate lists and logged incidents to feed both fan and command views.
    """
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

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
        incidents = db.query(Incident).order_by(Incident.created_at.desc()).limit(50).all()
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

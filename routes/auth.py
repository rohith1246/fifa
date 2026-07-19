import logging
from typing import Any
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from database import SessionLocal
from models import User
from services.security import escape_html

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


@app_route_register := auth_bp.route("/register", methods=["GET", "POST"])
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
            return redirect(url_for("auth.register"))

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for("auth.register"))

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("auth.register"))

        db = SessionLocal()
        try:
            exists = db.query(User).filter(User.username == username).first()
            if exists:
                flash("Username is already taken.", "danger")
                return redirect(url_for("auth.register"))

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
            return redirect(url_for("dashboard.dashboard"))
        except Exception as e:
            db.rollback()
            logger.error(f"Error during registration: {e}")
            flash("An error occurred. Please try again.", "danger")
            return redirect(url_for("auth.register"))
        finally:
            db.close()

    return render_template("register.html")


@app_route_login := auth_bp.route("/login", methods=["GET", "POST"])
def login() -> Any:
    """
    Handles secure profile login credentials check.
    """
    if request.method == "POST":
        username = escape_html(request.form.get("username", "").strip())
        password = request.form.get("password")

        if not username or not password:
            flash("Please enter both username and password.", "danger")
            return redirect(url_for("auth.login"))

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user or not check_password_hash(user.password_hash, password):
                flash("Invalid credentials.", "danger")
                return redirect(url_for("auth.login"))

            session.permanent = True
            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role

            flash("Welcome back!", "success")
            return redirect(url_for("dashboard.dashboard"))
        finally:
            db.close()

    return render_template("login.html")


@auth_bp.route("/logout")
def logout() -> Any:
    """
    Destroys session references on logout.
    """
    session.clear()
    return redirect(url_for("dashboard.index"))

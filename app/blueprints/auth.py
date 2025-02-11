# blueprints/auth.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from flask_login import login_user, logout_user, login_required, current_user, login_manager
#from werkzeug.security import generate_password_hash, check_password_hash
from app.models import Person, Result, GameNightGame, Game, Player
from app.utils import flash_if_no_action
from sqlalchemy import func
from app.extensions import db, bcrypt
import sys

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email").strip().lower()
        password = request.form.get("password")

        user = Person.query.filter(func.lower(Person.email)==email).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)

            if user.temp_pass:
                flash("Please update your password.", "warning")
                return redirect(url_for("auth.update_password"))
            return redirect(request.args.get("next") or url_for("main.index"))
        else:
            flash("Invalid email or password.", "error")

    return render_template("login.html")

@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/signup", methods=["GET", "POST"])
@flash_if_no_action("Please provide all required fields to sign up.", "error")
def signup():
    if request.method == "POST":
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        email = request.form.get("email").strip().lower()
        password = request.form.get("password")

        existing_user = Person.query.filter_by(email=email).first()
        if existing_user:
            flash("An account with this email already exists.", "error")
            return redirect(url_for("auth.signup"))

        hashed_password = bcrypt.generate_password_hash(password)
        new_user = Person(first_name=first_name, last_name=last_name, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("signup.html")


@auth_bp.route("/forgot_password", methods=["GET", "POST"]) #UPDATE TO OLD FORMAT
@flash_if_no_action("Please enter your email address to reset your password.", "error")
def forgot_password():
    from utils import send_email
    import secrets

    if request.method == "POST":
        email = request.form.get("email").strip().lower()
        user = Person.query.filter_by(email=email).first()

        if user:
            temp_password = secrets.token_urlsafe(8)
            user.password = bcrypt.generate_password_hash(temp_password).decode('utf-8')
            user.temp_pass = True
            db.session.commit()

            subject = "Password Reset for Game Night App"
            html_body = f"""
            <p>Hello {user.first_name},</p>
            <p>Your temporary password is: <strong>{temp_password}</strong></p>
            <p>Please log in and change your password.</p>
            """
            send_email(user.email, subject, html_body)

            flash("A temporary password has been sent to your email.", "success")
            return redirect(url_for("auth.login"))
        else:
            flash("Email not found.", "error")

    return render_template("forgot_password.html")


@auth_bp.route("/update_password", methods=["GET", "POST"])
@login_required
def update_password():
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        user = current_user

        if not bcrypt.check_password_hash(user.password, current_password):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("auth.update_password"))

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return redirect(url_for("auth.update_password"))

        user.password = bcrypt.generate_password_hash(new_password)
        user.temp_pass = False
        db.session.commit()

        flash("Password updated successfully.", "success")
        return redirect(url_for("main.index"))

    return render_template("update_password.html")


@auth_bp.route("/manage_user", methods=["GET", "POST"])
@login_required
def manage_user():
    """Displays user profile and game stats."""
    user = current_user

    games_played = (
        db.session.query(func.count(Result.id))
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(Player, Result.player_id == Player.id)
        .filter(Player.people_id == user.id)
        .scalar() or 0
    )

    total_wins = (
        db.session.query(func.count(Result.id))
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(Player, Result.player_id == Player.id)
        .filter(Player.people_id == user.id, Result.position == 1)
        .scalar() or 0
    )

    win_percentage = round((total_wins / games_played * 100) if games_played > 0 else 0, 2)

    def get_game_stats(game_id):
        """Fetch win percentage, total wins, and average finish for a game."""
        total_wins = (
            db.session.query(func.count(Result.id))
            .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
            .join(Player, Result.player_id == Player.id)
            .filter(Player.people_id == user.id, GameNightGame.game_id == game_id, Result.position == 1)
            .scalar()
        )
        total_played = (
            db.session.query(func.count(Result.id))
            .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
            .join(Player, Result.player_id == Player.id)
            .filter(Player.people_id == user.id, GameNightGame.game_id == game_id)
            .scalar()
        )
        avg_finish = (
            db.session.query(func.avg(Result.position))
            .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
            .join(Player, Result.player_id == Player.id)
            .filter(Player.people_id == user.id, GameNightGame.game_id == game_id)
            .scalar()
        )

        win_percentage = round((total_wins / total_played * 100) if total_played > 0 else 0, 2)
        avg_finish = round(avg_finish, 2) if avg_finish else None

        return total_wins, win_percentage, avg_finish

    most_played_game_query = (
        db.session.query(Game, func.count(Result.id).label("play_count"))
        .join(GameNightGame, GameNightGame.game_id == Game.id)
        .join(Result, Result.game_night_game_id == GameNightGame.id)
        .join(Player, Result.player_id == Player.id)
        .filter(Player.people_id == user.id)
        .group_by(Game.id)
        .order_by(func.count(Result.id).desc())
        .first()
    )

    most_played_game = most_played_game_query[0] if most_played_game_query else None
    most_played_stats = get_game_stats(most_played_game.id) if most_played_game else (0, 0, None)

    most_wins_game_query = (
        db.session.query(Game, func.count(Result.id).label("win_count"))
        .join(GameNightGame, GameNightGame.game_id == Game.id)
        .join(Result, Result.game_night_game_id == GameNightGame.id)
        .join(Player, Result.player_id == Player.id)
        .filter(Player.people_id == user.id, Result.position == 1)
        .group_by(Game.id)
        .order_by(func.count(Result.id).desc())
        .first()
    )

    most_wins_game = most_wins_game_query[0] if most_wins_game_query else None
    most_wins_stats = get_game_stats(most_wins_game.id) if most_wins_game else (0, 0, None)

    stats = {
        "games_played": games_played,
        "wins": total_wins,
        "win_percentage": win_percentage,
        "most_played_game": most_played_game,
        "most_played_stats": most_played_stats,
        "most_wins_game": most_wins_game,
        "most_wins_stats": most_wins_stats
    }

    return render_template("manage_user.html", person=user, stats=stats)

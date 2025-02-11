# blueprints/admin.py

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, Person
from app.utils import admin_required

admin_bp = Blueprint("admin", __name__)

@admin_bp.route("/admin", methods=["GET"])
@login_required
@admin_required
def admin_page():
    """Displays the admin panel with a list of users."""
    people = Person.query.all()
    return render_template("admin_page.html", people=people)


@admin_bp.route("/toggle_admin_status/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def toggle_admin_status(user_id):
    """Toggles the admin status of a user."""
    user = Person.query.get_or_404(user_id)
    user.admin = not user.admin
    action = "promoted to" if user.admin else "demoted from"
    db.session.commit()
    flash(f"{user.first_name} {user.last_name} has been {action} admin.", "success")
    return redirect(url_for("admin.admin_page"))


@admin_bp.route("/remove_user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def remove_user(user_id):
    """Removes a user from the system (only by an admin)."""
    user = Person.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("You cannot remove yourself.", "error")
    else:
        db.session.delete(user)
        db.session.commit()
        flash(f"{user.first_name} {user.last_name} has been removed.", "success")

    return redirect(url_for("admin.admin_page"))

@admin_bp.route("/add_person", methods=["GET", "POST"])
@login_required
@admin_required
def add_person():
    """Allows admins to manually add a new person to the system."""
    if request.method == "POST":
        first_name = request.form.get("first_name").strip()
        last_name = request.form.get("last_name").strip()

        if not first_name or not last_name:
            flash("Both first name and last name are required.", "error")
            return redirect(url_for("admin.add_person"))

        person = Person(first_name=first_name, last_name=last_name)
        db.session.add(person)
        db.session.commit()

        flash("Person added successfully.", "success")
        return redirect(url_for("admin.add_person"))

    return render_template("add_person.html")
import hashlib
from datetime import timedelta

from sqlalchemy import func

from app.extensions import bcrypt
from app.models import AuthThrottle, Person, db
from app.utils import send_email

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_BYTES = 72  # bcrypt refuses anything longer


def password_problem(password):
    """What's wrong with a new password, or None if it's fine. The one rule
    for signup, reset, and changing it from the profile."""
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        return f"Use at least {PASSWORD_MIN_LENGTH} characters for your password."
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        return "That password is too long; keep it under 70 characters."
    return None


def hash_password(password):
    return bcrypt.generate_password_hash(password).decode("utf-8")


# Throttling lives in the database so every worker and thread sees the same
# counts (Flask-Limiter's only shared backends are Redis/Memcached/MongoDB).
LOGIN_WINDOW = 15 * 60
LOGIN_EMAIL_LIMIT = 10  # failed sign-ins for one email per window
LOGIN_IP_LIMIT = 30  # failed sign-ins from one address per window
FORGOT_WINDOW = 60 * 60
FORGOT_EMAIL_LIMIT = 3  # reset emails to one address per window
FORGOT_IP_LIMIT = 10  # reset requests from one address per window
TOO_MANY_LOGINS = "Too many sign-in attempts. Wait a few minutes and try again."


def _throttle_on():
    from flask import current_app

    return current_app.config.get("AUTH_THROTTLE", True)


def _email_key(kind, email):
    return f"{kind}:email:" + hashlib.sha256(email.encode("utf-8")).hexdigest()[:40]


def _over_limit(key, limit, window):
    since = func.now() - timedelta(seconds=window)
    count = AuthThrottle.query.filter(
        AuthThrottle.key == key, AuthThrottle.created_at > since
    ).count()
    return count >= limit


def _record(*keys):
    AuthThrottle.query.filter(AuthThrottle.created_at < func.now() - timedelta(days=1)).delete(
        synchronize_session=False
    )
    db.session.add_all([AuthThrottle(key=key) for key in keys if key])
    db.session.commit()


def login(email, password, ip=None):
    """Authenticate user and return success status, message, and user instance."""
    if not email or not password:
        return False, "Enter your email and password.", None
    throttle = _throttle_on()
    email_key, ip_key = _email_key("login", email), f"login:ip:{ip}" if ip else None
    if throttle and (
        _over_limit(email_key, LOGIN_EMAIL_LIMIT, LOGIN_WINDOW)
        or (ip_key and _over_limit(ip_key, LOGIN_IP_LIMIT, LOGIN_WINDOW))
    ):
        return False, TOO_MANY_LOGINS, None
    user = Person.query.filter(func.lower(Person.email) == email).first()
    if user and user.password and bcrypt.check_password_hash(user.password, password):
        return True, "Login successful.", user
    if throttle:
        _record(email_key, ip_key)
    return False, "Invalid email or password.", None


def signup(first_name, last_name, email, password):
    """Complete signup for a pre-created user by setting email and password."""
    email = email.strip().lower()
    first_name = first_name.strip().lower()
    last_name = last_name.strip().lower()

    problem = password_problem(password)
    if problem:
        return False, problem

    # Email already taken by any user
    if Person.query.filter(func.lower(Person.email) == email).first():
        return False, "An account with this email already exists."

    # Try to find a matching person by name
    user = (
        Person.query.filter_by(active=True)
        .filter(func.lower(Person.first_name) == first_name)
        .filter(func.lower(Person.last_name) == last_name)
        .first()
    )

    if not user:
        return False, "No matching user found with that name. Please contact an admin."

    if user.email or user.password:
        return (
            False,
            "This user has already completed signup. Please use the forgot password or contact an admin.",
        )

    # Set email and password
    user.email = email
    user.password = hash_password(password)
    db.session.commit()

    return True, "Signup completed successfully! You can now log in."


RESET_MAX_AGE = 60 * 60  # reset links work for an hour
FORGOT_MESSAGE = "If that email has an account, we've sent a link to reset the password."


def _reset_serializer():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def _password_fingerprint(user):
    """A digest of the stored password hash: changes whenever the password
    does, without putting any of the hash itself in a readable token."""
    return hashlib.sha256((user.password or "").encode("utf-8")).hexdigest()[:32]


def make_reset_token(user):
    # Carries a fingerprint of the current password, so the link stops working
    # once the password has been changed (i.e. it can only be used once).
    return _reset_serializer().dumps({"id": user.id, "pw": _password_fingerprint(user)})


def user_for_reset_token(token):
    """The person a reset link is for, or None if it's invalid, used or expired."""
    from itsdangerous import BadSignature, SignatureExpired

    try:
        data = _reset_serializer().loads(token, max_age=RESET_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(Person, data.get("id"))
    if user is None or not user.active or _password_fingerprint(user) != data.get("pw"):
        return None
    return user


def forgot_password(email, ip=None):
    """Email a one-time reset link. Says the same thing whether or not the
    email has an account, so the form can't be used to find out."""
    from flask import url_for

    email = (email or "").strip().lower()
    if _throttle_on():
        email_key, ip_key = _email_key("forgot", email), f"forgot:ip:{ip}" if ip else None
        if _over_limit(email_key, FORGOT_EMAIL_LIMIT, FORGOT_WINDOW) or (
            ip_key and _over_limit(ip_key, FORGOT_IP_LIMIT, FORGOT_WINDOW)
        ):
            return True, FORGOT_MESSAGE  # same answer; just don't send
        _record(email_key, ip_key)
    user = Person.query.filter(func.lower(Person.email) == email).first()
    if user and user.active and user.password:
        link = url_for("auth.reset_password", token=make_reset_token(user), _external=True)
        html_body = f"""
        <p>Hello {user.first_name},</p>
        <p>Someone asked to reset your Game Night password. If it was you, use this link
        within the next hour:</p>
        <p><a href="{link}">{link}</a></p>
        <p>If you didn't ask, you can ignore this email; your password hasn't changed.</p>
        """
        try:
            send_email(user.email, "Reset your Game Night password", html_body)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Password reset email failed for %s", user.id)
    return True, FORGOT_MESSAGE


def reset_password(user, new_password, confirm_password):
    problem = password_problem(new_password)
    if problem:
        return False, problem
    if new_password != confirm_password:
        return False, "The passwords don't match."
    user.password = hash_password(new_password)
    user.rotate_session_token()  # sign out anyone else using the old password
    db.session.commit()
    return True, "Password changed. You can sign in now."


def update_password(user, current_password, new_password, confirm_password):
    """Update user password if the current password is correct."""
    if not user.password or not bcrypt.check_password_hash(user.password, current_password or ""):
        return False, "Current password is incorrect."

    problem = password_problem(new_password)
    if problem:
        return False, problem
    if new_password != confirm_password:
        return False, "New passwords do not match."

    user.password = hash_password(new_password)
    user.rotate_session_token()  # the caller logs this session back in
    db.session.commit()

    return True, "Password updated successfully."


def update_profile(user, current_password, email, new_password, confirm_password):
    """Change email and/or password from the profile page. Either change
    needs the current password."""
    email = (email or "").strip().lower()
    new_password = new_password or ""
    changing_email = email != (user.email or "")
    if not changing_email and not new_password:
        return False, "Nothing to update."
    if not user.password or not bcrypt.check_password_hash(user.password, current_password or ""):
        return False, "Current password is incorrect."

    if changing_email:
        if not email or "@" not in email:
            return False, "Enter a valid email address."
        taken = Person.query.filter(func.lower(Person.email) == email, Person.id != user.id).first()
        if taken:
            return False, "An account with this email already exists."
        user.email = email

    if new_password:
        problem = password_problem(new_password)
        if problem:
            return False, problem
        if new_password != confirm_password:
            return False, "New passwords do not match."
        user.password = hash_password(new_password)
        user.rotate_session_token()  # the caller logs this session back in

    db.session.commit()
    changed = [what for what, did in (("Email", changing_email), ("password", new_password)) if did]
    return True, f"{' and '.join(changed).capitalize()} updated."

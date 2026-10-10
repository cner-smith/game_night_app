# tests/blueprints/test_auth_security.py
"""Login redirects, password policy, reset tokens, sessions, throttling, invites."""

import pytest

from tests.conftest import login


@pytest.mark.parametrize(
    "next_url",
    [
        "/\\evil.com",
        "\\\\evil.com",
        "/\\/evil.com",
        "//evil.com",
        "https://evil.com",
        "javascript:alert(1)",
        "http:/evil.com",
    ],
)
def test_login_rejects_offsite_next(client, make_person, next_url):
    ann = make_person("Ann")
    resp = client.post(
        "/login",
        query_string={"next": next_url},
        data={"email": ann.email, "password": "password"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_login_keeps_local_next(client, make_person):
    ann = make_person("Ann")
    resp = client.post(
        "/login",
        query_string={"next": "/games?sort=name"},
        data={"email": ann.email, "password": "password"},
    )
    assert resp.headers["Location"] == "/games?sort=name"


@pytest.mark.parametrize("data", [{"email": "x@test.invalid"}, {}, {"password": "pw"}])
def test_login_with_missing_fields_is_a_friendly_error(client, make_person, data):
    ann = make_person("Ann")
    data = {k: (ann.email if k == "email" else v) for k, v in data.items()}
    resp = client.post("/login", data=data)
    assert resp.status_code == 200
    assert b"Enter your email and password." in resp.data


def test_password_policy_is_shared():
    from app.services.auth_services import password_problem

    assert password_problem(None) and password_problem("") and password_problem("seven77")
    assert password_problem("é" * 37)  # 74 bytes: bcrypt refuses more than 72
    assert password_problem("eight888") is None


def test_update_password_enforces_policy(client, make_person):
    ann = make_person("Ann")
    login(client, ann)
    old = ann.password
    resp = client.post(
        "/update_password",
        data={"current_password": "password", "new_password": "short", "confirm_password": "short"},
    )
    assert b"at least 8 characters" in resp.data
    assert ann.password == old


def test_profile_enforces_policy(client, make_person):
    ann = make_person("Ann")
    login(client, ann)
    old = ann.password
    resp = client.post(
        "/manage_user",
        data={
            "current_password": "password",
            "email": ann.email,
            "new_password": "x" * 80,
            "confirm_password": "x" * 80,
        },
        follow_redirects=True,
    )
    assert b"too long" in resp.data
    assert ann.password == old


def test_signup_enforces_policy():
    from app.services import auth_services

    ok, message = auth_services.signup("Shorty", "Pw", "shorty@test.invalid", "abc")
    assert not ok and "at least 8 characters" in message


def test_reset_token_does_not_carry_the_password_hash(make_person):
    from itsdangerous import URLSafeTimedSerializer

    from app.services import auth_services

    ann = make_person("Ann")
    token = auth_services.make_reset_token(ann)
    payload = URLSafeTimedSerializer("x").loads_unsafe(token)[1]
    assert ann.password[-12:] not in str(payload)
    assert auth_services.user_for_reset_token(token) == ann
    ann.password = auth_services.hash_password("another-password")
    assert auth_services.user_for_reset_token(token) is None


def _fresh_request():
    from flask import g

    g.pop("_login_user", None)  # the suite shares one app context; see conftest


def _logged_in(client):
    _fresh_request()
    return client.get("/manage_user").status_code == 200


@pytest.mark.parametrize("route", ["/update_password", "/manage_user"])
def test_changing_password_logs_out_other_sessions(app, make_person, route):
    ann = make_person("Ann")
    here, there = app.test_client(), app.test_client()
    login(here, ann)
    login(there, ann)
    assert _logged_in(here) and _logged_in(there)
    data = {
        "current_password": "password",
        "new_password": "new-password-1",
        "confirm_password": "new-password-1",
        "email": ann.email,
    }
    _fresh_request()
    here.post(route, data=data)
    assert _logged_in(here)
    assert not _logged_in(there)


def test_reset_and_deactivation_log_out_sessions(app, make_person, make_night):
    from app.services import admin_services, auth_services

    ann, adm = make_person("Ann"), make_person("Adm", admin=True)
    make_night(ann)
    c = app.test_client()
    login(c, ann)
    auth_services.reset_password(ann, "reset-password", "reset-password")
    assert not _logged_in(c)
    login(c, ann, "reset-password")
    assert _logged_in(c)
    admin_services.remove_user(ann.id, adm.id)
    admin_services.restore_user(ann.id)
    assert not _logged_in(c)


def test_sessions_from_before_tokens_still_work_until_a_change(app, make_person):
    """Sessions holding the bare id (from before this change) stay valid
    until the person's token is first set."""
    from app.extensions import db

    ann = make_person("Ann")
    assert ann.session_token is None and ann.get_id() == str(ann.id)
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(ann.id)
        sess["_fresh"] = True
    assert _logged_in(c)
    ann.rotate_session_token()
    db.session.commit()
    assert not _logged_in(c)


@pytest.fixture()
def throttled(app, db):
    from app.models import AuthThrottle

    AuthThrottle.query.delete()
    db.session.commit()
    app.config["AUTH_THROTTLE"] = True
    yield
    app.config["AUTH_THROTTLE"] = False
    db.session.rollback()
    AuthThrottle.query.delete()
    db.session.commit()


def test_login_is_throttled_per_email(client, make_person, throttled):
    from app.services import auth_services

    ann = make_person("Ann")
    for _ in range(auth_services.LOGIN_EMAIL_LIMIT):
        resp = client.post("/login", data={"email": ann.email, "password": "wrong-guess"})
        assert b"Invalid email or password." in resp.data
    resp = client.post("/login", data={"email": ann.email, "password": "password"})
    assert resp.status_code == 429 and b"Too many sign-in attempts" in resp.data


def test_login_is_throttled_per_address(client, make_person, throttled, monkeypatch):
    from app.services import auth_services

    monkeypatch.setattr(auth_services, "LOGIN_IP_LIMIT", 3)
    for n in range(3):
        client.post("/login", data={"email": f"nobody{n}@test.invalid", "password": "x"})
    ann = make_person("Ann")
    resp = client.post("/login", data={"email": ann.email, "password": "password"})
    assert resp.status_code == 429


def test_forgot_password_is_throttled_and_answers_the_same(
    client, make_person, throttled, monkeypatch
):
    from markupsafe import escape

    from app.services import auth_services

    ann = make_person("Ann")
    sent = []
    monkeypatch.setattr(auth_services, "send_email", lambda to, subj, body: sent.append(to))
    answers = set()
    for _ in range(auth_services.FORGOT_EMAIL_LIMIT + 2):
        resp = client.post("/forgot_password", data={"email": ann.email}, follow_redirects=True)
        answers.add(str(escape(auth_services.FORGOT_MESSAGE)) in resp.get_data(as_text=True))
    resp = client.post(
        "/forgot_password", data={"email": "nobody@test.invalid"}, follow_redirects=True
    )
    answers.add(str(escape(auth_services.FORGOT_MESSAGE)) in resp.get_data(as_text=True))
    assert answers == {True}
    assert len(sent) == auth_services.FORGOT_EMAIL_LIMIT

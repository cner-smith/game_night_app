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

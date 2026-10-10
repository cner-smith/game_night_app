# tests/blueprints/test_auth_security.py
"""Login redirects, password policy, reset tokens, sessions, throttling, invites."""

import pytest


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

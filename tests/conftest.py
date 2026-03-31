import os
import unittest.mock

import pytest

from app import create_app
from app.config import Config
from app.extensions import db as _db


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    WTF_CSRF_ENABLED = False
    # Flask-Login sets LOGIN_DISABLED=True when TESTING=True, which bypasses
    # @login_required and makes current_user.is_authenticated always True.
    # Override so auth behaviour is real in tests.
    LOGIN_DISABLED = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL")
    BCRYPT_LOG_ROUNDS = 4  # fast hashing in tests


@pytest.fixture(scope="session")
def app():
    """Create a test Flask app using the test PostgreSQL database."""
    from app.extensions import sess

    # Disable Flask-Session so Flask uses built-in cookie sessions (no file I/O).
    # Patch APScheduler to prevent background threads firing against a closed DB.
    with unittest.mock.patch("app.start_schedulers"), unittest.mock.patch.object(sess, "init_app"):
        application = create_app(TestConfig)

    # Do NOT set SERVER_NAME — it breaks url_for() resolution in tests.
    return application


@pytest.fixture(scope="session")
def db(app):
    """Run all migrations (tables + views) for the test session."""
    from flask_migrate import upgrade

    with app.app_context():
        upgrade()
        yield _db
        _db.session.remove()
        _db.engine.dispose()


@pytest.fixture()
def client(app, db):
    """Flask test client — no nested app_context (session-scoped db already holds one)."""
    with app.test_client() as client:
        yield client


@pytest.fixture()
def auth_client(app, db):
    """Test client pre-logged-in as a standard user."""
    from app.extensions import bcrypt
    from app.models import Person

    _db.session.rollback()
    Person.query.filter_by(email="test@example.com").delete()
    _db.session.commit()

    user = Person(
        first_name="Test",
        last_name="User",
        email="test@example.com",
        password=bcrypt.generate_password_hash("password", rounds=4).decode("utf-8"),
        admin=False,
        owner=False,
    )
    _db.session.add(user)
    _db.session.commit()

    with app.test_client() as client:
        client.post("/login", data={"email": "test@example.com", "password": "password"})
        yield client

    _db.session.rollback()
    Person.query.filter_by(email="test@example.com").delete()
    _db.session.commit()


@pytest.fixture()
def admin_client(app, db):
    """Test client pre-logged-in as an admin user."""
    from app.extensions import bcrypt
    from app.models import Person, Poll

    _db.session.rollback()
    # Delete polls created by this admin before deleting the person (FK constraint).
    existing = Person.query.filter_by(email="admin@example.com").first()
    if existing:
        Poll.query.filter_by(created_by=existing.id).delete()
        _db.session.delete(existing)
        _db.session.commit()

    admin = Person(
        first_name="Admin",
        last_name="User",
        email="admin@example.com",
        password=bcrypt.generate_password_hash("password", rounds=4).decode("utf-8"),
        admin=True,
        owner=False,
    )
    _db.session.add(admin)
    _db.session.commit()

    with app.test_client() as client:
        client.post("/login", data={"email": "admin@example.com", "password": "password"})
        yield client

    _db.session.rollback()
    existing = Person.query.filter_by(email="admin@example.com").first()
    if existing:
        Poll.query.filter_by(created_by=existing.id).delete()
        _db.session.delete(existing)
        _db.session.commit()


@pytest.fixture(scope="session")
def seed_data(db, app):
    """Minimal seed: one Game, one GameNight for routes with path params."""
    import datetime

    from app.models import Game, GameNight

    game = Game(name="Test Game", bgg_id=1)
    _db.session.add(game)
    _db.session.flush()

    game_night = GameNight(date=datetime.date.today())
    _db.session.add(game_night)
    _db.session.commit()

    yield {"game_id": game.id, "game_night_id": game_night.id}

    _db.session.delete(game_night)
    _db.session.delete(game)
    _db.session.commit()

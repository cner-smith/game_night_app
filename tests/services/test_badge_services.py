import datetime
import uuid
import pytest
from sqlalchemy.exc import IntegrityError
from app.extensions import db as _db
from app.models import Badge, Game, GameNight, GameNightGame, Person, PersonBadge, Player, Result


def test_badge_model_can_be_created(app, db):
    with app.app_context():
        badge = Badge(key=f"test_{uuid.uuid4().hex[:6]}", name="Test", description="desc", icon="🎯")
        _db.session.add(badge)
        _db.session.commit()
        assert badge.id is not None
        _db.session.delete(badge)
        _db.session.commit()


def test_person_badge_unique_constraint(app, db):
    with app.app_context():
        badge = Badge(key=f"uniq_{uuid.uuid4().hex[:6]}", name="Uniq", description="d", icon="⭐")
        person = Person(
            first_name="A", last_name="B",
            email=f"badge_test_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([badge, person])
        _db.session.flush()

        pb = PersonBadge(person_id=person.id, badge_id=badge.id)
        _db.session.add(pb)
        _db.session.commit()

        pb2 = PersonBadge(person_id=person.id, badge_id=badge.id)
        _db.session.add(pb2)
        with pytest.raises(IntegrityError):
            _db.session.flush()

        _db.session.rollback()
        PersonBadge.query.filter_by(person_id=person.id).delete()
        _db.session.delete(badge)
        _db.session.delete(person)
        _db.session.commit()


@pytest.fixture()
def badge_night(app, db):
    """A finalized game night with two players and one game result."""
    with app.app_context():
        game = Game(name=f"BGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        winner = Person(
            first_name="Winner", last_name="One",
            email=f"winner_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        loser = Person(
            first_name="Loser", last_name="Two",
            email=f"loser_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([game, winner, loser])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=1), final=True)
        _db.session.add(gn)
        _db.session.flush()

        winner_player = Player(game_night_id=gn.id, people_id=winner.id)
        loser_player = Player(game_night_id=gn.id, people_id=loser.id)
        _db.session.add_all([winner_player, loser_player])
        _db.session.flush()

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()

        _db.session.add(Result(game_night_game_id=gng.id, player_id=winner_player.id, position=1, score=10))
        _db.session.add(Result(game_night_game_id=gng.id, player_id=loser_player.id, position=2, score=5))
        _db.session.commit()

        yield {
            "game_night": gn, "game": game,
            "winner": winner, "loser": loser,
            "winner_player": winner_player, "loser_player": loser_player,
            "gng": gng,
        }

        Result.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(gng)
        _db.session.delete(winner_player)
        _db.session.delete(loser_player)
        _db.session.delete(gn)
        _db.session.delete(winner)
        _db.session.delete(loser)
        _db.session.delete(game)
        _db.session.commit()


def test_evaluate_badges_awards_first_blood(app, db, badge_night):
    from app.services.badge_services import evaluate_badges_for_night

    with app.app_context():
        winner_id = badge_night["winner"].id
        gn_id = badge_night["game_night"].id

        PersonBadge.query.filter_by(person_id=winner_id).delete()
        _db.session.commit()

        evaluate_badges_for_night(gn_id)

        badge = Badge.query.filter_by(key="first_blood").first()
        earned = PersonBadge.query.filter_by(person_id=winner_id, badge_id=badge.id).first()
        assert earned is not None


def test_evaluate_badges_does_not_duplicate(app, db, badge_night):
    from app.services.badge_services import evaluate_badges_for_night

    with app.app_context():
        winner_id = badge_night["winner"].id
        gn_id = badge_night["game_night"].id

        PersonBadge.query.filter_by(person_id=winner_id).delete()
        _db.session.commit()

        evaluate_badges_for_night(gn_id)
        evaluate_badges_for_night(gn_id)  # second call should not duplicate

        badge = Badge.query.filter_by(key="first_blood").first()
        count = PersonBadge.query.filter_by(person_id=winner_id, badge_id=badge.id).count()
        assert count == 1


def test_evaluate_badges_does_not_raise_on_bad_night(app, db):
    from app.services.badge_services import evaluate_badges_for_night

    with app.app_context():
        # Non-existent game night ID — should not raise
        evaluate_badges_for_night(999999)

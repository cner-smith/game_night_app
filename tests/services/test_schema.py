"""Database-level rules: foreign key cascades and one-row-per-thing constraints."""

import datetime

import pytest

from app.extensions import db as _db
from app.models import (
    TrackerSession,
    TrackerTeam,
    TrackerValue,
    tracker_team_players,
)
from app.services import tracker_services
from app.services.game_night_services import manage_attendees
from tests.services.test_badge_rules import World


@pytest.fixture()
def w(app, db):
    world = World()
    yield world
    _db.session.rollback()
    night_ids = [n.id for n in world.nights]
    from app.models import GameNightGame

    gng_ids = [g.id for g in GameNightGame.query.filter(GameNightGame.game_night_id.in_(night_ids))]
    TrackerSession.query.filter(TrackerSession.game_night_game_id.in_(gng_ids)).delete()
    _db.session.commit()
    world.cleanup()


def _tracked_night(w, mode):
    a, b = w.person(), w.person()
    gn = w.night(datetime.date(1840, 1, 1), [a, b], final=False)
    gng = w.play(gn, w.game(), {})
    _db.session.commit()
    session = tracker_services.get_or_create_configuring_session(gng.id)
    tracker_services.add_field(
        session.id, type="counter", label="VP", starting_value=0, is_score_field=True
    )
    pl_a, pl_b = gn._players[a.id].id, gn._players[b.id].id
    tracker_services.launch_session(
        session.id,
        mode=mode,
        teams_data=[{"name": "Reds", "player_ids": [pl_a, pl_b]}],
        player_ids=[pl_a, pl_b],
    )
    return gn, a, b, session.id, pl_b


def test_removing_attendee_with_tracker_values_deletes_them(w):
    gn, a, b, sid, pl_b = _tracked_night(w, "individual")
    assert TrackerValue.query.filter_by(player_id=pl_b).count() == 1

    assert manage_attendees(gn, [a.id]) is None
    _db.session.commit()

    assert TrackerValue.query.filter_by(player_id=pl_b).count() == 0
    assert TrackerValue.query.filter_by(tracker_session_id=sid).count() == 1


def test_removing_attendee_on_a_tracker_team_drops_them_from_it(w):
    gn, a, b, sid, pl_b = _tracked_night(w, "teams")
    team = TrackerTeam.query.filter_by(tracker_session_id=sid).one()

    assert manage_attendees(gn, [a.id]) is None
    _db.session.commit()

    members = _db.session.execute(
        tracker_team_players.select().where(tracker_team_players.c.team_id == team.id)
    ).all()
    assert [m.player_id for m in members] == [gn._players[a.id].id]

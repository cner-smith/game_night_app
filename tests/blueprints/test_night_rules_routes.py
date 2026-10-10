"""Night rules through the routes: who can save official results, and what
malformed input gets back."""

import pytest

from app.extensions import db as _db
from app.models import Result, TrackerSession
from app.services import tracker_services
from tests.conftest import login
from tests.night_world import World


@pytest.fixture()
def w(app, db):
    world = World()
    yield world
    world.cleanup()


def _tracked(w):
    """A night hosted by Host with player Ann; an active tracker where Ann
    has 7 and Host has 3."""
    host, ann = w.person("Host"), w.person("Ann")
    gn = w.night(host, ann, host=host)
    gng = w.play(gn)
    session = tracker_services.get_or_create_configuring_session(gng.id)
    field = session.fields[0]
    ph, pa = w.player(gn, host), w.player(gn, ann)
    tracker_services.launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[ph.id, pa.id]
    )
    tracker_services.update_value(
        session.id, field.id, entity_type="player", entity_id=pa.id, delta=7
    )
    tracker_services.update_value(
        session.id, field.id, entity_type="player", entity_id=ph.id, delta=3
    )
    return host, ann, gn, gng, session, ph, pa


# --- tracker: only the host saves or discards ---------------------------------


def test_participant_cannot_save_tracker_results(client, w):
    host, ann, gn, gng, session, ph, pa = _tracked(w)
    login(client, ann)
    resp = client.post(
        f"/tracker/{session.id}/save",
        data={f"position_p_{pa.id}": "1", f"position_p_{ph.id}": "2"},
    )
    assert resp.status_code == 403
    assert Result.query.filter_by(game_night_game_id=gng.id).count() == 0
    assert _db.session.get(TrackerSession, session.id).status == "active"


def test_participant_cannot_discard_or_confirm_tracker(client, w):
    host, ann, gn, gng, session, ph, pa = _tracked(w)
    login(client, ann)
    assert client.post(f"/tracker/{session.id}/discard").status_code == 403
    assert _db.session.get(TrackerSession, session.id) is not None
    assert client.get(f"/tracker/{session.id}/end").status_code == 403
    page = client.get(f"/tracker/{session.id}").get_data(as_text=True)
    assert "End Game" not in page and "Discard" not in page


def test_participant_can_still_track_scores(client, w):
    host, ann, gn, gng, session, ph, pa = _tracked(w)
    login(client, ann)
    field = session.fields[0]
    resp = client.post(
        f"/tracker/{session.id}/value",
        data={"field_id": field.id, "entity_type": "player", "entity_id": pa.id, "delta": "1"},
    )
    assert resp.status_code == 200


def test_saved_scores_come_from_the_tracker_not_the_form(client, w):
    host, ann, gn, gng, session, ph, pa = _tracked(w)
    login(client, host)
    resp = client.post(
        f"/tracker/{session.id}/save",
        data={
            f"position_p_{pa.id}": "1",
            f"score_p_{pa.id}": "999",
            f"position_p_{ph.id}": "2",
            f"score_p_{ph.id}": "-5",
        },
    )
    assert resp.status_code == 302
    scores = {
        r.player_id: (r.position, r.score)
        for r in Result.query.filter_by(game_night_game_id=gng.id)
    }
    assert scores == {pa.id: (1, 7), ph.id: (2, 3)}


def test_host_can_adjust_places_on_confirm(client, w):
    host, ann, gn, gng, session, ph, pa = _tracked(w)
    login(client, host)
    client.post(
        f"/tracker/{session.id}/save",
        data={f"position_p_{pa.id}": "2", f"position_p_{ph.id}": "1"},
    )
    places = {r.player_id: r.position for r in Result.query.filter_by(game_night_game_id=gng.id)}
    assert places == {pa.id: 2, ph.id: 1}


def test_missing_places_default_to_the_computed_ranking(client, w):
    host, ann, gn, gng, session, ph, pa = _tracked(w)
    login(client, host)
    client.post(f"/tracker/{session.id}/save", data={})
    places = {r.player_id: r.position for r in Result.query.filter_by(game_night_game_id=gng.id)}
    assert places == {pa.id: 1, ph.id: 2}


@pytest.mark.parametrize("bad", ["0", "3", "abc", "-1"])
def test_out_of_range_places_are_refused(client, w, bad):
    host, ann, gn, gng, session, ph, pa = _tracked(w)
    login(client, host)
    resp = client.post(
        f"/tracker/{session.id}/save",
        data={f"position_p_{pa.id}": bad, f"position_p_{ph.id}": "1"},
    )
    assert resp.status_code == 302 and "/end" in resp.headers["Location"]
    assert Result.query.filter_by(game_night_game_id=gng.id).count() == 0

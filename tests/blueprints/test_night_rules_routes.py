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


# --- finalize / reopen are explicit, not a toggle -----------------------------


def _played_night(w):
    host, ann = w.person("Host"), w.person("Ann")
    gn = w.night(host, ann, host=host, address="1 Main St")
    w.play(gn, positions={host: 1, ann: 2})
    return host, ann, gn


def test_finalizing_twice_keeps_the_night_final(client, w):
    from app.models import PersonBadge

    host, ann, gn = _played_night(w)
    login(client, host)
    resp = client.post(f"/game_night/{gn.id}/finalize")
    assert resp.status_code == 302 and "finalized=1" in resp.headers["Location"]
    _db.session.refresh(gn)
    assert gn.final and gn.address is None
    badges = PersonBadge.query.filter_by(game_night_id=gn.id).count()
    assert badges > 0

    # A double-click or a second tab posts again: still final, badges kept.
    resp = client.post(f"/game_night/{gn.id}/finalize")
    assert resp.status_code == 302 and "finalized=1" not in resp.headers["Location"]
    _db.session.refresh(gn)
    assert gn.final
    assert PersonBadge.query.filter_by(game_night_id=gn.id).count() == badges


def test_unfinalize_is_explicit_and_idempotent(client, w):
    from app.models import PersonBadge

    host, ann, gn = _played_night(w)
    login(client, host)
    client.post(f"/game_night/{gn.id}/finalize")
    client.post(f"/game_night/{gn.id}/unfinalize")
    _db.session.refresh(gn)
    assert not gn.final
    assert PersonBadge.query.filter_by(game_night_id=gn.id).count() == 0
    client.post(f"/game_night/{gn.id}/unfinalize")
    _db.session.refresh(gn)
    assert not gn.final


def test_toggle_route_no_longer_flips_final(client, w):
    host, ann, gn = _played_night(w)
    login(client, host)
    client.post(f"/game_night/{gn.id}/finalize")
    client.post(f"/game_night/{gn.id}/toggle/final")
    _db.session.refresh(gn)
    assert gn.final


def test_players_cannot_finalize(client, w):
    host, ann, gn = _played_night(w)
    login(client, ann)
    client.post(f"/game_night/{gn.id}/finalize")
    _db.session.refresh(gn)
    assert not gn.final


# --- log results checks its body ---------------------------------------------


def _log_setup(w):
    host, ann = w.person("Host"), w.person("Ann")
    gn = w.night(host, ann, host=host)
    gng = w.play(gn)
    return host, gn, gng, w.player(gn, host), w.player(gn, ann)


def _log(client, gn, gng, body):
    return client.post(f"/game_night/{gn.id}/log_results/{gng.id}", json=body)


def test_log_results_saves_scores_and_places(client, w):
    host, gn, gng, ph, pa = _log_setup(w)
    login(client, host)
    resp = _log(
        client,
        gn,
        gng,
        {
            str(ph.id): {"user_id": str(ph.id), "score": 12, "position": 1},
            str(pa.id): {"user_id": str(pa.id), "score": None, "position": None},
        },
    )
    assert resp.status_code == 302
    got = {r.player_id: (r.position, r.score) for r in gng.results}
    assert got == {ph.id: (1, 12), pa.id: (None, None)}


def test_log_results_refuses_a_player_from_another_night(client, w):
    host, gn, gng, ph, pa = _log_setup(w)
    stranger = w.person("Stranger")
    other = w.night(stranger)
    ps = w.player(other, stranger)
    login(client, host)
    resp = _log(client, gn, gng, {str(ps.id): {"user_id": ps.id, "score": 1, "position": 1}})
    assert resp.status_code == 400
    assert Result.query.filter_by(player_id=ps.id).count() == 0


@pytest.mark.parametrize(
    "entry",
    [
        {"score": 1, "position": 1},  # no user_id
        {"user_id": "x", "score": 1, "position": 1},
        {"user_id": "PID", "score": "lots", "position": 1},
        {"user_id": "PID", "score": 1, "position": [1]},
        "not an object",
    ],
)
def test_log_results_rejects_malformed_entries(client, w, entry):
    host, gn, gng, ph, pa = _log_setup(w)
    if isinstance(entry, dict) and entry.get("user_id") == "PID":
        entry = {**entry, "user_id": ph.id}
    login(client, host)
    resp = _log(client, gn, gng, {str(ph.id): entry})
    assert resp.status_code == 400
    assert Result.query.filter_by(game_night_game_id=gng.id).count() == 0


def test_log_results_rejects_a_non_object_body(client, w):
    host, gn, gng, ph, pa = _log_setup(w)
    login(client, host)
    assert _log(client, gn, gng, [1, 2]).status_code == 400


def test_log_results_page_404s_for_another_nights_game(client, w):
    host, gn, gng, ph, pa = _log_setup(w)
    other = w.night(host, host=host)
    other_gng = w.play(other)
    login(client, host)
    assert client.get(f"/game_night/{gn.id}/log_results/{gng.id}").status_code == 200
    assert client.get(f"/game_night/{gn.id}/log_results/{other_gng.id}").status_code == 404
    resp = _log(client, gn, other_gng, {str(ph.id): {"user_id": ph.id, "score": 1, "position": 1}})
    assert resp.status_code == 404

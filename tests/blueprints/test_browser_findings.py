"""Regressions for what a click-through of the merged app turned up: blank
result rows, out-of-range numbers, lost flashes and anchors, pages that only
refused on submit, and the RSVP poll closing with voting."""

import uuid

import pytest

from app.extensions import db as _db
from app.models import GameNight, Poll, Result
from tests.conftest import login
from tests.night_world import World


@pytest.fixture()
def w(app, db):
    world = World()
    yield world
    world.cleanup()


def _setup(w, **night):
    host, ann = w.person("Host"), w.person("Ann")
    gn = w.night(host, ann, host=host, **night)
    gng = w.play(gn)
    return host, ann, gn, gng, w.player(gn, host), w.player(gn, ann)


def _log(client, gn, gng, body):
    return client.post(f"/game_night/{gn.id}/log_results/{gng.id}", json=body)


def _entry(player, score, position):
    return {"user_id": player.id, "score": score, "position": position}


# --- log results ---------------------------------------------------------------


def test_blank_entries_save_no_result_row(client, w):
    host, ann, gn, gng, ph, pa = _setup(w)
    login(client, host)
    _log(client, gn, gng, {"a": _entry(ph, 12, 1), "b": _entry(pa, None, None)})
    assert {r.player_id for r in Result.query.filter_by(game_night_game_id=gng.id)} == {ph.id}


def test_clearing_an_entry_removes_its_result(client, w):
    host, ann, gn, gng, ph, pa = _setup(w)
    login(client, host)
    _log(client, gn, gng, {"a": _entry(ph, 12, 1), "b": _entry(pa, 3, 2)})
    _log(client, gn, gng, {"a": _entry(ph, 12, 1), "b": _entry(pa, None, None)})
    assert {r.player_id for r in Result.query.filter_by(game_night_game_id=gng.id)} == {ph.id}


def test_out_of_range_score_is_a_400_not_a_500(client, w):
    host, ann, gn, gng, ph, pa = _setup(w)
    login(client, host)
    resp = _log(client, gn, gng, {"a": _entry(ph, 99999999999, 1)})
    assert resp.status_code == 400
    assert "too big" in resp.get_json()["error"]


def test_saved_results_answer_with_where_to_go_and_keep_the_flash(client, w):
    host, ann, gn, gng, ph, pa = _setup(w)
    login(client, host)
    resp = _log(client, gn, gng, {"a": _entry(ph, 12, 1)})
    assert resp.status_code == 200
    assert resp.get_json()["redirect"].endswith(f"/game_night/{gn.id}#played")
    assert "Results logged" in client.get(f"/game_night/{gn.id}").get_data(as_text=True)


# --- tracker save lands on #played -----------------------------------------------


def test_tracker_save_redirects_to_played(client, w):
    from app.services import tracker_services

    host, ann, gn, gng, ph, pa = _setup(w)
    session = tracker_services.get_or_create_configuring_session(gng.id)
    tracker_services.launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[ph.id, pa.id]
    )
    login(client, host)
    resp = client.post(f"/tracker/{session.id}/save")
    assert resp.status_code == 302 and resp.location.endswith(f"/game_night/{gn.id}#played")


# --- closing voting ----------------------------------------------------------------


def test_closing_voting_says_so_and_keeps_the_rsvp_poll_open(client, w):
    host, ann, gn, gng, ph, pa = _setup(w)
    rsvp = Poll(
        title="RSVP",
        created_by=host.id,
        token=uuid.uuid4().hex,
        game_night_id=gn.id,
        availability=True,
    )
    _db.session.add(rsvp)
    _db.session.commit()
    w.polls.append(rsvp.id)
    login(client, host)
    resp = client.post(f"/game_night/{gn.id}/toggle/closed", follow_redirects=True)
    assert "Voting closed." in resp.get_data(as_text=True)
    _db.session.refresh(rsvp)
    assert rsvp.closed is False
    resp = client.post(f"/game_night/{gn.id}/toggle/closed", follow_redirects=True)
    assert "Voting reopened." in resp.get_data(as_text=True)


# --- pages that can't be used say so up front ---------------------------------------


def test_nominate_page_redirects_when_voting_is_closed(client, w):
    host, ann, gn, gng, ph, pa = _setup(w, closed=True)
    login(client, ann)
    resp = client.get(f"/game_night/{gn.id}/nominate")
    assert resp.status_code == 302 and resp.location.endswith(f"/game_night/{gn.id}")


@pytest.mark.parametrize("path", ["log_results/{gng}", "add_game"])
def test_editing_pages_redirect_on_a_finalized_night(client, w, path):
    host, ann, gn, gng, ph, pa = _setup(w, final=True)
    login(client, host)
    resp = client.get(f"/game_night/{gn.id}/" + path.format(gng=gng.id))
    assert resp.status_code == 302 and resp.location.endswith(f"/game_night/{gn.id}")


def test_new_tracker_on_a_finalized_night_redirects_with_a_message(client, w):
    host, ann, gn, gng, ph, pa = _setup(w, final=True)
    login(client, host)
    resp = client.get(f"/game_night/{gng.id}/tracker/new", follow_redirects=True)
    assert resp.status_code == 200 and "finalized" in resp.get_data(as_text=True)


# --- public recap ---------------------------------------------------------------------


def test_public_recap_leaves_out_the_notes(client, w):
    host, ann, gn, gng, ph, pa = _setup(w, final=True, notes="Gate code 4321")
    client.post("/logout")
    page = client.get(f"/game_night/{gn.id}/recap").get_data(as_text=True)
    assert "Gate code 4321" not in page
    assert _db.session.get(GameNight, gn.id).notes == "Gate code 4321"

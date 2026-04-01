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
        PersonBadge.query.filter_by(game_night_id=gn.id).delete()
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


# ---------------------------------------------------------------------------
# Group A: single-night wins/placements
# ---------------------------------------------------------------------------

def test_first_blood_earns_on_first_win(app, db, badge_night):
    from app.services.badge_services import _check_first_blood
    with app.app_context():
        assert _check_first_blood(badge_night["winner"].id, badge_night["game_night"].id) is True


def test_first_blood_does_not_earn_for_loser(app, db, badge_night):
    from app.services.badge_services import _check_first_blood
    with app.app_context():
        assert _check_first_blood(badge_night["loser"].id, badge_night["game_night"].id) is False


@pytest.fixture()
def hat_trick_night(app, db):
    """A game night where one player wins 3 games."""
    with app.app_context():
        game = Game(name=f"HTGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        player_person = Person(
            first_name="HT", last_name="Player",
            email=f"ht_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        other = Person(
            first_name="Other", last_name="HT",
            email=f"other_ht_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([game, player_person, other])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=2), final=True)
        _db.session.add(gn)
        _db.session.flush()

        p1 = Player(game_night_id=gn.id, people_id=player_person.id)
        p2 = Player(game_night_id=gn.id, people_id=other.id)
        _db.session.add_all([p1, p2])
        _db.session.flush()

        gngs = []
        for i in range(3):
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=i + 1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=p1.id, position=1, score=10))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=p2.id, position=2, score=5))

        _db.session.commit()
        yield {"gn": gn, "player": player_person, "other": other, "gngs": gngs, "p1": p1, "p2": p2}

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        _db.session.delete(p1)
        _db.session.delete(p2)
        _db.session.delete(gn)
        _db.session.delete(player_person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_hat_trick_earns_with_3_wins(app, db, hat_trick_night):
    from app.services.badge_services import _check_hat_trick
    with app.app_context():
        assert _check_hat_trick(hat_trick_night["player"].id, hat_trick_night["gn"].id) is True


def test_hat_trick_does_not_earn_with_1_win(app, db, badge_night):
    from app.services.badge_services import _check_hat_trick
    with app.app_context():
        assert _check_hat_trick(badge_night["winner"].id, badge_night["game_night"].id) is False


def test_bench_warmer_earns_when_always_last(app, db, badge_night):
    from app.services.badge_services import _check_bench_warmer
    with app.app_context():
        assert _check_bench_warmer(badge_night["loser"].id, badge_night["game_night"].id) is True


def test_bench_warmer_does_not_earn_for_winner(app, db, badge_night):
    from app.services.badge_services import _check_bench_warmer
    with app.app_context():
        assert _check_bench_warmer(badge_night["winner"].id, badge_night["game_night"].id) is False


def test_jack_of_all_trades_earns_when_top_half(app, db, badge_night):
    # badge_night: 2 players, winner is position 1 (top half of 2 = 1)
    from app.services.badge_services import _check_jack_of_all_trades
    with app.app_context():
        assert _check_jack_of_all_trades(badge_night["winner"].id, badge_night["game_night"].id) is True


def test_jack_of_all_trades_does_not_earn_when_last(app, db, badge_night):
    from app.services.badge_services import _check_jack_of_all_trades
    with app.app_context():
        assert _check_jack_of_all_trades(badge_night["loser"].id, badge_night["game_night"].id) is False


@pytest.fixture()
def diplomat_night(app, db):
    """A game night where all players tied at position 1."""
    with app.app_context():
        game = Game(name=f"DipGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        p1 = Person(first_name="D1", last_name="P", email=f"dip1_{uuid.uuid4().hex[:6]}@test.invalid")
        p2 = Person(first_name="D2", last_name="P", email=f"dip2_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, p1, p2])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=3), final=True)
        _db.session.add(gn)
        _db.session.flush()

        pl1 = Player(game_night_id=gn.id, people_id=p1.id)
        pl2 = Player(game_night_id=gn.id, people_id=p2.id)
        _db.session.add_all([pl1, pl2])
        _db.session.flush()

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()
        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl1.id, position=1, score=10))
        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl2.id, position=1, score=10))
        _db.session.commit()

        yield {"gn": gn, "game": game, "p1": p1, "p2": p2, "pl1": pl1, "pl2": pl2, "gng": gng}

        Result.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(gng)
        _db.session.delete(pl1)
        _db.session.delete(pl2)
        _db.session.delete(gn)
        _db.session.delete(p1)
        _db.session.delete(p2)
        _db.session.delete(game)
        _db.session.commit()


def test_the_diplomat_earns_when_all_tied(app, db, diplomat_night):
    from app.services.badge_services import _check_the_diplomat
    with app.app_context():
        assert _check_the_diplomat(diplomat_night["p1"].id, diplomat_night["gn"].id) is True


def test_the_diplomat_does_not_earn_when_not_all_tied(app, db, badge_night):
    from app.services.badge_services import _check_the_diplomat
    with app.app_context():
        assert _check_the_diplomat(badge_night["winner"].id, badge_night["game_night"].id) is False


def test_opening_night_earns_on_first_night(app, db, badge_night):
    from app.services.badge_services import _check_opening_night
    with app.app_context():
        # Find the actual first game night in the DB
        from app.models import GameNight as GN
        first = GN.query.order_by(GN.id).first()
        assert first is not None
        # If badge_night is the first, it earns; otherwise test opening_night with the first night
        person_id = badge_night["winner"].id
        gn_id = badge_night["game_night"].id
        # Only earns when game_night_id IS the first night
        result = _check_opening_night(person_id, gn_id)
        if first.id == gn_id:
            assert result is True
        else:
            assert result is False


# ---------------------------------------------------------------------------
# Group B: history-aware single-night badges
# ---------------------------------------------------------------------------

@pytest.fixture()
def redemption_setup(app, db):
    """Player lost game X 3 times, then wins it tonight."""
    with app.app_context():
        game = Game(name=f"RGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(first_name="Red", last_name="Arc",
                        email=f"red_{uuid.uuid4().hex[:6]}@test.invalid")
        other = Person(first_name="Other", last_name="Red",
                       email=f"other_red_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, person, other])
        _db.session.flush()

        nights = []
        players = []
        gngs = []
        for i, (delta, pos) in enumerate([(30, 2), (20, 2), (10, 2), (1, 1)]):
            gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=delta), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)

            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.append(pl)

            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)

            _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=pos, score=5))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=1 if pos != 1 else 2, score=10))

        _db.session.commit()
        tonight = nights[-1]
        yield {"person": person, "game": game, "tonight": tonight, "nights": nights, "gngs": gngs, "players": players, "other": other}

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in players:
            _db.session.delete(pl)
        for gn in nights:
            # also delete the op Players for each night before deleting the night
            Player.query.filter_by(game_night_id=gn.id).delete()
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        PersonBadge.query.filter_by(person_id=person.id).delete()
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_redemption_arc_earns_after_3_losses(app, db, redemption_setup):
    from app.services.badge_services import _check_redemption_arc
    with app.app_context():
        assert _check_redemption_arc(
            redemption_setup["person"].id,
            redemption_setup["tonight"].id
        ) is True


def test_redemption_arc_does_not_earn_without_enough_losses(app, db, badge_night):
    from app.services.badge_services import _check_redemption_arc
    with app.app_context():
        assert _check_redemption_arc(badge_night["winner"].id, badge_night["game_night"].id) is False


@pytest.fixture()
def rematch_setup(app, db):
    """Player attended two consecutive nights, both including same game."""
    with app.app_context():
        game = Game(name=f"RM {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(first_name="Re", last_name="Match",
                        email=f"rm_{uuid.uuid4().hex[:6]}@test.invalid")
        other = Person(first_name="Oth", last_name="RM",
                       email=f"othrm_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, person, other])
        _db.session.flush()

        nights = []
        players = []
        gngs = []
        for delta in [5, 1]:
            gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=delta), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)

            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.append((pl, op))

            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=1, score=10))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=2, score=5))

        _db.session.commit()
        yield {"person": person, "tonight": nights[-1], "nights": nights, "gngs": gngs, "players": players}

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl_pair in players:
            for pl in pl_pair:
                _db.session.delete(pl)
        for gn in nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        PersonBadge.query.filter_by(person_id=person.id).delete()
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_the_rematch_earns_when_same_game_back_to_back(app, db, rematch_setup):
    from app.services.badge_services import _check_the_rematch
    with app.app_context():
        assert _check_the_rematch(rematch_setup["person"].id, rematch_setup["tonight"].id) is True


def test_the_rematch_does_not_earn_on_first_night(app, db, badge_night):
    from app.services.badge_services import _check_the_rematch
    with app.app_context():
        # Only one night exists for this person in badge_night
        assert _check_the_rematch(badge_night["winner"].id, badge_night["game_night"].id) is False


@pytest.fixture()
def dark_horse_setup(app, db):
    """Player loses first 3 games in one night, wins the 4th."""
    with app.app_context():
        game = Game(name=f"DH {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(first_name="Dark", last_name="Horse",
                        email=f"dh_{uuid.uuid4().hex[:6]}@test.invalid")
        other = Person(first_name="Oth", last_name="DH",
                       email=f"othdh_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, person, other])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=1), final=True)
        _db.session.add(gn)
        _db.session.flush()

        pl = Player(game_night_id=gn.id, people_id=person.id)
        op = Player(game_night_id=gn.id, people_id=other.id)
        _db.session.add_all([pl, op])
        _db.session.flush()

        gngs = []
        positions = [2, 2, 2, 1]  # lose 3, win last
        for i, pos in enumerate(positions):
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=i + 1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=pos, score=5))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=3 - pos, score=5))

        _db.session.commit()
        yield {"person": person, "gn": gn, "gngs": gngs, "pl": pl, "op": op, "other": other, "game": game}

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        _db.session.delete(pl)
        _db.session.delete(op)
        PersonBadge.query.filter_by(game_night_id=gn.id).delete()
        _db.session.delete(gn)
        PersonBadge.query.filter_by(person_id=person.id).delete()
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_dark_horse_earns_after_3_losses_then_win(app, db, dark_horse_setup):
    from app.services.badge_services import _check_dark_horse
    with app.app_context():
        assert _check_dark_horse(dark_horse_setup["person"].id, dark_horse_setup["gn"].id) is True


def test_dark_horse_does_not_earn_with_only_3_games(app, db, hat_trick_night):
    from app.services.badge_services import _check_dark_horse
    with app.app_context():
        # hat_trick_night has 3 games, not 4
        assert _check_dark_horse(hat_trick_night["other"].id, hat_trick_night["gn"].id) is False

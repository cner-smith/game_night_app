"""Badge evaluation service.

Public API:
    evaluate_badges_for_night(game_night_id) -> None
    get_person_badges(person_id) -> list[PersonBadge]
"""

import logging

from sqlalchemy import func

from app.extensions import db
from app.models import (
    Badge,
    Game,
    GameNight,
    GameNightGame,
    GameNominations,
    OwnedBy,
    Person,
    PersonBadge,
    Player,
    Result,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Badge definitions — single source of truth for key → uses_night_id mapping
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Checker stubs — each returns bool
# ---------------------------------------------------------------------------

def _check_first_blood(person_id: int, game_night_id: int) -> bool:
    return (
        db.session.query(Result)
        .join(Player, Result.player_id == Player.id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(
            Player.people_id == person_id,
            Result.position == 1,
            GameNight.final.is_(True),
        )
        .first()
    ) is not None


def _check_hat_trick(person_id: int, game_night_id: int) -> bool:
    wins = (
        db.session.query(func.count(Result.id))
        .join(Player, Result.player_id == Player.id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position == 1,
        )
        .scalar()
    )
    return (wins or 0) >= 3

def _check_veteran(person_id: int, game_night_id: int) -> bool:
    count = (
        db.session.query(func.count(Player.id))
        .join(GameNight, Player.game_night_id == GameNight.id)
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
        .scalar()
    )
    return (count or 0) >= 25

def _check_kingslayer(person_id: int, game_night_id: int) -> bool:
    top = (
        db.session.query(Player.people_id, func.count(Result.id).label("wins"))
        .join(Result, Player.id == Result.player_id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(Result.position == 1, GameNight.final.is_(True))
        .group_by(Player.people_id)
        .order_by(db.text("wins DESC"))
        .first()
    )
    if not top or top.people_id == person_id:
        return False

    top_winner_id = top.people_id
    top_results = {
        r.game_night_game_id: r.position
        for r in (
            db.session.query(Result.game_night_game_id, Result.position)
            .join(Player, Result.player_id == Player.id)
            .filter(Player.people_id == top_winner_id, Result.position.isnot(None))
            .all()
        )
    }
    person_tonight = (
        db.session.query(Result.game_night_game_id, Result.position)
        .join(Player, Result.player_id == Player.id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position.isnot(None),
        )
        .all()
    )
    for gng_id, pos in person_tonight:
        if gng_id in top_results and pos < top_results[gng_id]:
            return True
    return False

def _check_collector(person_id: int, game_night_id: int) -> bool:
    return OwnedBy.query.filter_by(person_id=person_id).count() >= 10

def _check_variety_pack(person_id: int, game_night_id: int) -> bool:
    count = (
        db.session.query(func.count(func.distinct(GameNightGame.game_id)))
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
        .scalar()
    )
    return (count or 0) >= 10

def _check_nemesis(person_id: int, game_night_id: int) -> bool:
    person_results = (
        db.session.query(Result.game_night_game_id, Result.position)
        .join(Player, Result.player_id == Player.id)
        .filter(Player.people_id == person_id, Result.position.isnot(None))
        .all()
    )
    nemesis_counts: dict = {}
    for gng_id, pos in person_results:
        opponents = (
            db.session.query(Player.people_id)
            .join(Result, Player.id == Result.player_id)
            .filter(
                Result.game_night_game_id == gng_id,
                Player.people_id != person_id,
                Result.position < pos,
                Result.position.isnot(None),
            )
            .all()
        )
        for (opp_id,) in opponents:
            nemesis_counts[opp_id] = nemesis_counts.get(opp_id, 0) + 1
    return any(count >= 5 for count in nemesis_counts.values())

def _check_redemption_arc(person_id: int, game_night_id: int) -> bool:
    won_tonight = (
        db.session.query(GameNightGame.game_id)
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position == 1,
        )
        .all()
    )
    for (game_id,) in won_tonight:
        prior_losses = (
            db.session.query(func.count(Result.id))
            .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
            .join(Player, Result.player_id == Player.id)
            .join(GameNight, GameNightGame.game_night_id == GameNight.id)
            .filter(
                Player.people_id == person_id,
                GameNightGame.game_id == game_id,
                GameNightGame.game_night_id != game_night_id,
                Result.position != 1,
                GameNight.final.is_(True),
            )
            .scalar()
        )
        if (prior_losses or 0) >= 3:
            return True
    return False

def _check_night_owl(person_id: int, game_night_id: int) -> bool:
    current = db.session.get(GameNight, game_night_id)
    if not current:
        return False
    year, month = current.date.year, current.date.month
    count = (
        db.session.query(func.count(Player.id))
        .join(GameNight, Player.game_night_id == GameNight.id)
        .filter(
            Player.people_id == person_id,
            GameNight.final.is_(True),
            func.extract("year", GameNight.date) == year,
            func.extract("month", GameNight.date) == month,
        )
        .scalar()
    )
    return (count or 0) >= 5

def _check_gracious_host(person_id: int, game_night_id: int) -> bool:
    current = db.session.get(GameNight, game_night_id)
    if not current:
        return False
    year = current.date.year
    total_in_year = (
        db.session.query(func.count(GameNight.id))
        .filter(GameNight.final.is_(True), func.extract("year", GameNight.date) == year)
        .scalar()
    )
    if not total_in_year:
        return False
    attended_in_year = (
        db.session.query(func.count(Player.id))
        .join(GameNight, Player.game_night_id == GameNight.id)
        .filter(
            Player.people_id == person_id,
            GameNight.final.is_(True),
            func.extract("year", GameNight.date) == year,
        )
        .scalar()
    )
    return attended_in_year == total_in_year

def _check_jack_of_all_trades(person_id: int, game_night_id: int) -> bool:
    person_results = (
        db.session.query(GameNightGame.id.label("gng_id"), Result.position)
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position.isnot(None),
        )
        .all()
    )
    if not person_results:
        return False
    for row in person_results:
        total = (
            db.session.query(func.count(Result.id))
            .filter(Result.game_night_game_id == row.gng_id, Result.position.isnot(None))
            .scalar()
        )
        if row.position > (total + 1) // 2:
            return False
    return True

def _check_upset_special(person_id: int, game_night_id: int) -> bool:
    tonight_gng_ids = [
        r.id
        for r in GameNightGame.query.filter_by(game_night_id=game_night_id).all()
    ]
    for gng_id in tonight_gng_ids:
        person_pos = (
            db.session.query(Result.position)
            .join(Player, Result.player_id == Player.id)
            .filter(
                Player.people_id == person_id,
                Result.game_night_game_id == gng_id,
                Result.position.isnot(None),
            )
            .scalar()
        )
        if person_pos is None:
            continue

        beaten = (
            db.session.query(Player.people_id)
            .join(Result, Player.id == Result.player_id)
            .filter(
                Result.game_night_game_id == gng_id,
                Player.people_id != person_id,
                Result.position > person_pos,
                Result.position.isnot(None),
            )
            .all()
        )
        for (opp_id,) in beaten:
            prior = (
                db.session.query(Result.game_night_game_id)
                .join(Player, Result.player_id == Player.id)
                .filter(
                    Player.people_id == opp_id,
                    Result.game_night_game_id.in_(
                        db.session.query(Result.game_night_game_id)
                        .join(Player, Result.player_id == Player.id)
                        .filter(
                            Player.people_id == person_id,
                            Result.game_night_game_id.notin_(tonight_gng_ids),
                        )
                    ),
                )
                .all()
            )
            if len(prior) < 5:
                continue
            prior_gng_ids = [r.game_night_game_id for r in prior]
            opp_wins = 0
            for pgng_id in prior_gng_ids:
                p_pos = (
                    db.session.query(Result.position)
                    .join(Player, Result.player_id == Player.id)
                    .filter(Player.people_id == person_id, Result.game_night_game_id == pgng_id)
                    .scalar()
                )
                o_pos = (
                    db.session.query(Result.position)
                    .join(Player, Result.player_id == Player.id)
                    .filter(Player.people_id == opp_id, Result.game_night_game_id == pgng_id)
                    .scalar()
                )
                if p_pos and o_pos and o_pos < p_pos:
                    opp_wins += 1
            if opp_wins / len(prior_gng_ids) >= 0.8:
                return True
    return False

def _check_bench_warmer(person_id: int, game_night_id: int) -> bool:
    person_results = (
        db.session.query(GameNightGame.id.label("gng_id"), Result.position)
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position.isnot(None),
        )
        .all()
    )
    if not person_results:
        return False
    for row in person_results:
        max_pos = (
            db.session.query(func.max(Result.position))
            .filter(Result.game_night_game_id == row.gng_id, Result.position.isnot(None))
            .scalar()
        )
        if row.position != max_pos:
            return False
    return True

def _check_grudge_match(person_id: int, game_night_id: int) -> bool:
    person_gng_ids = [
        r.game_night_game_id
        for r in (
            db.session.query(Result.game_night_game_id)
            .join(Player, Result.player_id == Player.id)
            .filter(Player.people_id == person_id)
            .all()
        )
    ]
    if not person_gng_ids:
        return False

    result = (
        db.session.query(
            GameNightGame.game_id,
            Player.people_id.label("opponent_id"),
            func.count(GameNightGame.id).label("shared"),
        )
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            GameNightGame.id.in_(person_gng_ids),
            Player.people_id != person_id,
        )
        .group_by(GameNightGame.game_id, Player.people_id)
        .having(func.count(GameNightGame.id) >= 10)
        .first()
    )
    return result is not None

def _check_the_closer(person_id: int, game_night_id: int) -> bool:
    attended = (
        db.session.query(GameNight.id)
        .join(Player, GameNight.id == Player.game_night_id)
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
        .order_by(GameNight.date)
        .all()
    )
    if len(attended) < 5:
        return False

    streak = 0
    for (nid,) in attended:
        last_game = (
            GameNightGame.query.filter_by(game_night_id=nid)
            .order_by(GameNightGame.round.desc())
            .first()
        )
        if not last_game:
            streak = 0
            continue
        won_last = (
            db.session.query(Result)
            .join(Player, Result.player_id == Player.id)
            .filter(
                Player.people_id == person_id,
                Result.game_night_game_id == last_game.id,
                Result.position == 1,
            )
            .first()
        )
        if won_last:
            streak += 1
            if streak >= 5:
                return True
        else:
            streak = 0
    return False

def _check_opening_night(person_id: int, game_night_id: int) -> bool:
    first_night = GameNight.query.order_by(GameNight.id).first()
    if first_night is None or first_night.id != game_night_id:
        return False
    return (
        Player.query.filter_by(game_night_id=game_night_id, people_id=person_id).first()
        is not None
    )

def _check_winning_streak(person_id: int, game_night_id: int) -> bool:
    attended = (
        db.session.query(GameNight.id)
        .join(Player, GameNight.id == Player.game_night_id)
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
        .order_by(GameNight.date)
        .all()
    )
    if len(attended) < 3:
        return False

    streak = 0
    for (nid,) in attended:
        won = (
            db.session.query(Result)
            .join(Player, Result.player_id == Player.id)
            .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
            .filter(
                Player.people_id == person_id,
                GameNightGame.game_night_id == nid,
                Result.position == 1,
            )
            .first()
        )
        if won:
            streak += 1
            if streak >= 3:
                return True
        else:
            streak = 0
    return False

def _check_the_diplomat(person_id: int, game_night_id: int) -> bool:
    if not Player.query.filter_by(game_night_id=game_night_id, people_id=person_id).first():
        return False
    games = GameNightGame.query.filter_by(game_night_id=game_night_id).all()
    if not games:
        return False
    for gng in games:
        non_first = (
            db.session.query(Result)
            .filter(
                Result.game_night_game_id == gng.id,
                Result.position != 1,
                Result.position.isnot(None),
            )
            .first()
        )
        if non_first:
            return False
    return True

def _check_early_bird(person_id: int, game_night_id: int) -> bool:
    # Player.created_at exists — use it to determine who registered first per night
    all_night_ids = [
        row[0] for row in db.session.query(Player.game_night_id).distinct().all()
    ]
    first_count = 0
    for nid in all_night_ids:
        first_player = Player.query.filter_by(game_night_id=nid).order_by(Player.created_at).first()
        if first_player and first_player.people_id == person_id:
            first_count += 1
    return first_count >= 10

def _check_the_rematch(person_id: int, game_night_id: int) -> bool:
    prev_player = (
        db.session.query(Player)
        .join(GameNight, Player.game_night_id == GameNight.id)
        .filter(
            Player.people_id == person_id,
            GameNight.id != game_night_id,
            GameNight.final.is_(True),
        )
        .order_by(GameNight.date.desc())
        .first()
    )
    if not prev_player:
        return False

    current_game_ids = {
        r.game_id
        for r in GameNightGame.query.filter_by(game_night_id=game_night_id).all()
    }
    prev_game_ids = {
        r.game_id
        for r in GameNightGame.query.filter_by(game_night_id=prev_player.game_night_id).all()
    }
    return bool(current_game_ids & prev_game_ids)

def _check_century_club(person_id: int, game_night_id: int) -> bool:
    count = (
        db.session.query(func.count(Result.id))
        .join(Player, Result.player_id == Player.id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
        .scalar()
    )
    return (count or 0) >= 100

def _check_dark_horse(person_id: int, game_night_id: int) -> bool:
    results = (
        db.session.query(
            GameNightGame.round,
            Result.position,
            GameNightGame.id.label("gng_id"),
        )
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position.isnot(None),
        )
        .order_by(GameNightGame.round)
        .all()
    )
    if len(results) < 4:
        return False
    for row in results[:3]:
        max_pos = (
            db.session.query(func.max(Result.position))
            .filter(
                Result.game_night_game_id == row.gng_id,
                Result.position.isnot(None),
            )
            .scalar()
        )
        if row.position != max_pos:
            return False
    return results[-1].position == 1

def _check_social_butterfly(person_id: int, game_night_id: int) -> bool:
    all_people_count = Person.query.count()
    distinct_partners = (
        db.session.query(func.count(func.distinct(Player.people_id)))
        .join(Result, Player.id == Result.player_id)
        .filter(
            Player.people_id != person_id,
            Result.game_night_game_id.in_(
                db.session.query(Result.game_night_game_id)
                .join(Player, Result.player_id == Player.id)
                .filter(Player.people_id == person_id)
            ),
        )
        .scalar()
    )
    return (distinct_partners or 0) >= all_people_count - 1


def _check_the_oracle(person_id: int, game_night_id: int) -> bool:
    finalized_nights = (
        db.session.query(GameNight.id).filter(GameNight.final.is_(True)).all()
    )
    oracle_count = 0
    for (nid,) in finalized_nights:
        nominations = (
            db.session.query(GameNominations.game_id)
            .join(Player, GameNominations.player_id == Player.id)
            .filter(Player.people_id == person_id, GameNominations.game_night_id == nid)
            .all()
        )
        for (game_id,) in nominations:
            played = GameNightGame.query.filter_by(game_night_id=nid, game_id=game_id).first()
            if not played:
                continue
            won = (
                db.session.query(Result)
                .join(Player, Result.player_id == Player.id)
                .filter(
                    Player.people_id == person_id,
                    Result.game_night_game_id == played.id,
                    Result.position == 1,
                )
                .first()
            )
            if won:
                oracle_count += 1
                break
    return oracle_count >= 5

def _check_founding_member(person_id: int, game_night_id: int) -> bool:
    first_five = (
        db.session.query(Player.people_id)
        .join(GameNight, Player.game_night_id == GameNight.id)
        .group_by(Player.people_id)
        .order_by(func.min(GameNight.date))
        .limit(5)
        .subquery()
    )
    return (
        db.session.query(first_five)
        .filter(first_five.c.people_id == person_id)
        .first()
        is not None
    )

def _check_most_wins(person_id: int, game_night_id: int) -> bool:
    rows = (
        db.session.query(Player.people_id, func.count(Result.id).label("wins"))
        .join(Result, Player.id == Result.player_id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(Result.position == 1, GameNight.final.is_(True))
        .group_by(Player.people_id)
        .order_by(db.text("wins DESC"))
        .all()
    )
    if not rows:
        return False
    max_wins = rows[0].wins
    if max_wins == 0:
        return False
    person_wins = next((r.wins for r in rows if r.people_id == person_id), 0)
    return person_wins == max_wins


def _stub(person_id: int, game_night_id: int) -> bool:
    """Placeholder — returns False until implemented."""
    return False


# ---------------------------------------------------------------------------
# Registry — maps badge key → checker function
# ---------------------------------------------------------------------------

_BADGE_REGISTRY: dict = {
    "first_blood": _check_first_blood,
    "hat_trick": _check_hat_trick,
    "veteran": _check_veteran,
    "kingslayer": _check_kingslayer,
    "collector": _check_collector,
    "variety_pack": _check_variety_pack,
    "nemesis": _check_nemesis,
    "redemption_arc": _check_redemption_arc,
    "night_owl": _check_night_owl,
    "gracious_host": _check_gracious_host,
    "jack_of_all_trades": _check_jack_of_all_trades,
    "upset_special": _check_upset_special,
    "bench_warmer": _check_bench_warmer,
    "grudge_match": _check_grudge_match,
    "the_closer": _check_the_closer,
    "opening_night": _check_opening_night,
    "winning_streak": _check_winning_streak,
    "the_diplomat": _check_the_diplomat,
    "early_bird": _check_early_bird,
    "the_rematch": _check_the_rematch,
    "century_club": _check_century_club,
    "dark_horse": _check_dark_horse,
    "social_butterfly": _check_social_butterfly,
    "the_oracle": _check_the_oracle,
    "founding_member": _check_founding_member,
    "most_wins": _check_most_wins,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_badges_for_night(game_night_id: int) -> None:
    """Evaluate all badges for all participants of the given finalized game night.

    Silently logs and returns on any error — must never raise to the caller.
    Relies on the uq_person_badge unique constraint to prevent duplicates;
    does NOT use an application-level pre-check (which would be a race condition).
    """
    from sqlalchemy.exc import IntegrityError

    try:
        game_night = db.session.get(GameNight, game_night_id)
        if game_night is None or not game_night.final:
            return

        participants = Player.query.filter_by(game_night_id=game_night_id).all()
        person_ids = [p.people_id for p in participants]

        badges = {b.key: b for b in Badge.query.all()}

        for badge_key, checker_fn in _BADGE_REGISTRY.items():
            badge = badges.get(badge_key)
            if badge is None:
                continue

            # Always store the triggering night so recap can show all awarded badges
            night_id_to_store = game_night_id

            for person_id in person_ids:
                try:
                    earned = checker_fn(person_id, game_night_id)
                except Exception:
                    logger.exception(
                        "Badge checker %s failed for person %s night %s",
                        badge_key, person_id, game_night_id,
                    )
                    continue

                if earned:
                    try:
                        db.session.add(PersonBadge(
                            person_id=person_id,
                            badge_id=badge.id,
                            game_night_id=night_id_to_store,
                        ))
                        db.session.flush()
                    except IntegrityError:
                        db.session.rollback()
                        # Already earned — unique constraint fired, skip silently
                        continue

        db.session.commit()

    except Exception:
        db.session.rollback()
        logger.exception("Badge evaluation failed for game night %s", game_night_id)


def get_person_badges(person_id: int) -> list:
    """Return all earned badges for a person, newest first."""
    from sqlalchemy.orm import joinedload
    return (
        PersonBadge.query
        .filter_by(person_id=person_id)
        .options(joinedload(PersonBadge.badge))
        .order_by(PersonBadge.earned_at.desc())
        .all()
    )

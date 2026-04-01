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

# keys where game_night_id is recorded on PersonBadge (the night that triggered it)
_NIGHT_LINKED = {
    "first_blood", "hat_trick", "kingslayer", "redemption_arc",
    "jack_of_all_trades", "upset_special", "bench_warmer", "opening_night",
    "the_diplomat", "the_rematch", "dark_horse",
}


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
    return _stub(person_id, game_night_id)

def _check_kingslayer(person_id: int, game_night_id: int) -> bool:
    return _stub(person_id, game_night_id)

def _check_collector(person_id: int, game_night_id: int) -> bool:
    return _stub(person_id, game_night_id)

def _check_variety_pack(person_id: int, game_night_id: int) -> bool:
    return _stub(person_id, game_night_id)

def _check_nemesis(person_id: int, game_night_id: int) -> bool:
    return _stub(person_id, game_night_id)

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
    return _stub(person_id, game_night_id)

def _check_gracious_host(person_id: int, game_night_id: int) -> bool:
    return _stub(person_id, game_night_id)

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
    return _stub(person_id, game_night_id)

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
    return _stub(person_id, game_night_id)

def _check_the_closer(person_id: int, game_night_id: int) -> bool:
    return _stub(person_id, game_night_id)

def _check_opening_night(person_id: int, game_night_id: int) -> bool:
    first_night = GameNight.query.order_by(GameNight.id).first()
    if first_night is None or first_night.id != game_night_id:
        return False
    return (
        Player.query.filter_by(game_night_id=game_night_id, people_id=person_id).first()
        is not None
    )

def _check_winning_streak(person_id: int, game_night_id: int) -> bool:
    return _stub(person_id, game_night_id)

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
    return _stub(person_id, game_night_id)

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
    return _stub(person_id, game_night_id)

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
    return _stub(person_id, game_night_id)

def _check_the_oracle(person_id: int, game_night_id: int) -> bool:
    return _stub(person_id, game_night_id)

def _check_founding_member(person_id: int, game_night_id: int) -> bool:
    return _stub(person_id, game_night_id)

def _check_most_wins(person_id: int, game_night_id: int) -> bool:
    return _stub(person_id, game_night_id)


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
    """
    try:
        game_night = db.session.get(GameNight, game_night_id)
        if game_night is None:
            return

        participants = Player.query.filter_by(game_night_id=game_night_id).all()
        person_ids = [p.people_id for p in participants]

        badges = {b.key: b for b in Badge.query.all()}

        for badge_key, checker_fn in _BADGE_REGISTRY.items():
            badge = badges.get(badge_key)
            if badge is None:
                continue

            night_id_to_store = game_night_id if badge_key in _NIGHT_LINKED else None

            for person_id in person_ids:
                already = PersonBadge.query.filter_by(
                    person_id=person_id, badge_id=badge.id
                ).first()
                if already:
                    continue

                try:
                    earned = checker_fn(person_id, game_night_id)
                except Exception:
                    logger.exception(
                        "Badge checker %s failed for person %s night %s",
                        badge_key, person_id, game_night_id,
                    )
                    continue

                if earned:
                    db.session.add(PersonBadge(
                        person_id=person_id,
                        badge_id=badge.id,
                        game_night_id=night_id_to_store,
                    ))

        db.session.commit()

    except Exception:
        db.session.rollback()
        logger.exception("Badge evaluation failed for game night %s", game_night_id)


def get_person_badges(person_id: int) -> list:
    """Return all earned badges for a person, newest first."""
    return (
        PersonBadge.query
        .filter_by(person_id=person_id)
        .order_by(PersonBadge.earned_at.desc())
        .all()
    )

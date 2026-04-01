# Achievement Badges — Design Spec

**Date:** 2026-03-31  
**Feature:** Feature 5 — Achievement Badges  
**Status:** Approved, ready for implementation

---

## Overview

Players earn badges for milestones and accomplishments across game nights. Badges are stored with an earned date — once earned, never lost. Badge evaluation runs automatically when a game night is finalized. Badges appear on the user stats page and on the game night recap page.

---

## Badge Catalog

26 badges. Defined in a `BADGE_DEFINITIONS` constant (list of dicts). Each entry has: `key`, `name`, `description`, `icon` (emoji).

Badges excluded (data not yet available):
- **Comeback Kid** — needs mid-game score snapshots
- **Strategist** — needs genre tags on games
- **Solo Carry** — needs cooperative/competitive flag on games
- **Eternal Bridesmaid** — game-level badge, not person-scoped; shown as a plain stat on the game page instead
- **Retirement Party** — dropped; rewarding absence doesn't fit the spirit of the app

### Full Badge List

| Key | Name | Icon | Description | game_night_id |
|-----|------|------|-------------|---------------|
| `first_blood` | First Blood | 🩸 | First time winning any game at a game night | set |
| `hat_trick` | Hat Trick | 🎩 | Win 3 games in a single game night session | set |
| `veteran` | Veteran | 🎖️ | Attend 25 game nights total | null |
| `kingslayer` | Kingslayer | 👑 | Beat the person with the most all-time wins in a head-to-head game | set |
| `collector` | Collector | 📦 | Own 10+ games in the group library | null |
| `variety_pack` | Variety Pack | 🎲 | Play 10 different unique games across any number of nights | null |
| `nemesis` | Nemesis | 😈 | One specific person has beaten you 5+ times in the same game (both present, both with a recorded position) | null |
| `redemption_arc` | Redemption Arc | 🔄 | Win a game you've previously lost 3+ times | set |
| `night_owl` | Night Owl | 🦉 | Attend 5 game nights in a single calendar month | null |
| `gracious_host` | Gracious Host | 🏠 | Attend every single game night recorded in a calendar year (perfect attendance, no floor on count) | null |
| `jack_of_all_trades` | Jack of All Trades | 🃏 | Finish in the top half in every game played at a single game night | set |
| `upset_special` | Upset Special | ⚡ | Beat a player whose win rate against you was 80%+ (min. 5 prior head-to-head games) | set |
| `bench_warmer` | Bench Warmer | 🪑 | Attend a game night but finish last in every game you played | set |
| `grudge_match` | Grudge Match | ⚔️ | Play the same game against the same opponent 10+ times (both present in same GameNightGame) | null |
| `the_closer` | The Closer | 🔒 | Win the last game (highest `round` in GameNightGame) at 5 consecutive game nights you attended | null |
| `opening_night` | Opening Night | 🎬 | Play in the very first game night ever recorded in the system (lowest game night id) | set |
| `winning_streak` | Winning Streak | 🔥 | Win at least one game at 3 consecutive game nights you attended | null |
| `the_diplomat` | The Diplomat | 🕊️ | Play a game night where every game ends in a tie or shared first place (position=1 for all players) | set |
| `early_bird` | Early Bird | 🐦 | Be the first person to join (lowest Player.created_at) 10 different game nights | null |
| `the_rematch` | The Rematch | 🔁 | Play the same game at back-to-back consecutive game nights you attended | set |
| `century_club` | Century Club | 💯 | Play in 100 total game night games across all nights | null |
| `dark_horse` | Dark Horse | 🐴 | Within a single game night: finish last in your first 3 games, then win the final game. Requires 4+ games in one night. Intended to be rare. | set |
| `social_butterfly` | Social Butterfly | 🦋 | Play at least one game with every other registered Person in the system | null |
| `the_oracle` | The Oracle | 🔮 | Nominate a game, that game gets played that night, and you win it — 5 times across different game nights | null |
| `founding_member` | Founding Member | 🏛️ | Be one of the first 5 distinct Person records (by Person.created_at) to ever appear as a Player in any game night | null |
| `most_wins` | Most Wins | 🥇 | Once held the record for most all-time wins (position=1) across the group | null |

**`game_night_id` column:** badges marked "set" record the specific game night where the badge was earned; badges marked "null" span cumulative history and are not attributed to a specific night.

---

## Data Model

### New table: `badges`

Seeded via raw SQL in the Alembic migration. Not user-editable.

```
id          INTEGER PRIMARY KEY
key         VARCHAR UNIQUE NOT NULL      -- e.g. "first_blood"
name        VARCHAR NOT NULL
description TEXT NOT NULL
icon        VARCHAR NOT NULL             -- emoji
```

### New table: `person_badges`

```
id              INTEGER PRIMARY KEY
person_id       INTEGER FK people.id NOT NULL
badge_id        INTEGER FK badges.id NOT NULL
earned_at       DATETIME NOT NULL (server_default=func.now())
game_night_id   INTEGER FK gamenights.id NULLABLE
```

Unique constraint: `(person_id, badge_id)` — a badge can only be earned once.

### Models

Add `PersonBadge` and `Badge` to `app/models.py`. Add `person_badges` relationship to `Person`.

---

## Badge Evaluation

### Trigger

In `game_night_services.py`, inside `toggle_game_night_field`: when `field == "final"` and the resulting value after toggle is `True`, call `evaluate_badges_for_night(game_night_id)`.

Badge evaluation must **not** be transactionally coupled to the finalization commit. Wrap the call in a try/except — if evaluation fails, log the error and continue. A badge evaluation failure must never block a game night from being finalized.

### New file: `app/services/badge_services.py`

**Public API:**

```python
def evaluate_badges_for_night(game_night_id: int) -> None:
    """Evaluate all badges for all participants of the given finalized game night.
    Errors are caught and logged; this must never raise to the caller."""

def get_person_badges(person_id: int) -> list[PersonBadge]:
    """Return all earned badges for a person, ordered by earned_at desc."""
```

**Internal structure:**

Each badge has a private checker function:
```python
def _check_first_blood(person_id: int, game_night_id: int) -> bool: ...
def _check_hat_trick(person_id: int, game_night_id: int) -> bool: ...
# ... one per badge
```

A registry maps badge keys to checker functions. `evaluate_badges_for_night` iterates all participants of the given night, calls each checker, and inserts a `PersonBadge` row if the badge isn't already earned. Checkers should use aggregating SQL queries (not Python-level loops) especially for history-spanning badges.

**Badge seeding:** Done via raw SQL `INSERT ... ON CONFLICT DO NOTHING` statements directly in the Alembic `upgrade()` function — no ORM dependency at migration time.

---

## Badge Checker Semantics

Precise definitions for the badges most likely to cause implementation ambiguity:

| Badge | Precise Logic |
|-------|--------------|
| **Nemesis** | Across all finalized game nights: one specific person appeared in the same `GameNightGame` as you and had a better `position` than you ≥ 5 times. Both players must have a non-null position recorded. |
| **Winning Streak** | Among the game nights the person *attended* (ordered by date): won at least one game (position=1) at 3 consecutive attended nights. Unattended nights do not break the streak. |
| **Dark Horse** | Within a single game night: the person played ≥ 4 games; their first 3 results (by `GameNightGame.round`) were last place; their final game (highest round) was a win (position=1). |
| **The Oracle** | The person nominated a game (via `GameNominations`) that was actually played that night (appears in `GameNightGame`), AND the person won that exact game (position=1 in that `GameNightGame`). This condition must be met at 5 different game nights. |
| **Gracious Host** | For a given calendar year: the person attended every finalized game night in that year. No minimum game night count — if the group only played twice, attending both qualifies. |
| **The Closer** | Among game nights the person attended: at 5 consecutive attended nights, the person won the game with the highest `round` number that night. |
| **Kingslayer** | At the time of the game night being finalized: the person with the highest all-time win count (position=1 count) is identified; if the badge earner appeared in the same `GameNightGame` and had a better position, the badge is awarded. |
| **Social Butterfly** | The person has appeared in at least one `GameNightGame` alongside every other `Person` registered in the system. Uses aggregate SQL — not Python iteration. |
| **Upset Special** | Among head-to-head matchups (same `GameNightGame`): the opponent must have won against the badge earner in ≥80% of prior meetings, with a minimum of 5 prior shared games. |

---

## Display

### User stats page (`user_stats.html`)

Add a "Badges" section at the top of the page. Shows earned badges as a grid: icon + name + earned date. Only earned badges shown — no locked/greyed-out display.

The blueprint route enriches the template context with `badges = get_person_badges(user_id)`.

### Recap page (`recap_game_night.html`)

Add a "Badges Earned Tonight" section. Queries `PersonBadge` where `game_night_id` matches. Shows person name + icon + badge name. Section is hidden if no badges were earned that night.

`get_recap_details()` gains a `badges_earned` key: list of `{person_name, badge_name, badge_icon}` dicts.

---

## Testing

### `tests/services/test_badge_services.py` (new)

- Each checker gets at least one "earns it" and one "doesn't earn it" case.
- Complex checkers (Kingslayer, Social Butterfly, Winning Streak, The Oracle, The Closer, Nemesis) get edge case tests.
- `evaluate_badges_for_night` de-duplication: verify a badge isn't awarded twice if evaluation runs again.
- `evaluate_badges_for_night` error isolation: verify a failing checker does not prevent other badges from being evaluated.

### `tests/blueprints/test_game_night.py` (extend)

- Finalize route triggers badge evaluation and writes to `person_badges`.
- Finalize route succeeds even if badge evaluation raises.

### `tests/blueprints/test_stats.py` (new)

- User stats route returns badges in context.

---

## Migration

One Alembic migration:
1. Create `badges` and `person_badges` tables.
2. Seed the badge catalog using raw SQL `INSERT INTO badges (...) VALUES ... ON CONFLICT (key) DO NOTHING` — no ORM, no app context dependency.

---

## Out of Scope

- Badge notifications / alerts (beyond recap page display)
- Badge revocation
- Admin badge management UI
- Genre-based or mid-game-score-based badges (deferred)
- Eternal Bridesmaid as a badge (shown as a plain stat on the game page)

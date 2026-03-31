# Achievement Badges — Design Spec

**Date:** 2026-03-31  
**Feature:** Feature 5 — Achievement Badges  
**Status:** Approved, ready for implementation

---

## Overview

Players earn badges for milestones and accomplishments across game nights. Badges are stored with an earned date — once earned, never lost. Badge evaluation runs automatically when a game night is finalized. Badges appear on the user stats page and on the game night recap page.

---

## Badge Catalog

27 badges across three rounds of brainstorming. Defined in a `BADGE_DEFINITIONS` constant (list of dicts). Each entry has: `key`, `name`, `description`, `icon` (emoji).

Badges excluded (data not yet available):
- **Comeback Kid** — needs mid-game score snapshots
- **Strategist** — needs genre tags on games
- **Solo Carry** — needs cooperative/competitive flag on games
- **Eternal Bridesmaid** — game-level badge, not person-scoped; shown as a plain stat on the game page instead

### Full Badge List

| Key | Name | Icon | Description |
|-----|------|------|-------------|
| `first_blood` | First Blood | 🩸 | First time winning any game at a game night |
| `hat_trick` | Hat Trick | 🎩 | Win 3 games in a single game night session |
| `veteran` | Veteran | 🎖️ | Attend 25 game nights total |
| `kingslayer` | Kingslayer | 👑 | Beat the person with the most all-time wins in a head-to-head game |
| `collector` | Collector | 📦 | Own 10+ games in the group library |
| `variety_pack` | Variety Pack | 🎲 | Play 10 different unique games across any number of nights |
| `nemesis` | Nemesis | 😈 | One specific person has beaten you 5+ times |
| `redemption_arc` | Redemption Arc | 🔄 | Win a game you've previously lost 3+ times |
| `night_owl` | Night Owl | 🦉 | Attend 5 game nights in a single calendar month |
| `gracious_host` | Gracious Host | 🏠 | Attend every game night for an entire calendar year |
| `jack_of_all_trades` | Jack of All Trades | 🃏 | Finish in the top half in every game played at a single game night |
| `upset_special` | Upset Special | ⚡ | Beat a player whose win rate against you was 80%+ |
| `bench_warmer` | Bench Warmer | 🪑 | Attend a game night but finish last in every game you played |
| `grudge_match` | Grudge Match | ⚔️ | Play the same game against the same opponent 10+ times |
| `the_closer` | The Closer | 🔒 | Win the last game played at 5 consecutive game nights |
| `retirement_party` | Retirement Party | 🎉 | Hasn't attended a game night in 6+ months |
| `opening_night` | Opening Night | 🎬 | Play in the very first game night ever recorded in the system |
| `winning_streak` | Winning Streak | 🔥 | Win at least one game at 3 consecutive game nights |
| `the_diplomat` | The Diplomat | 🕊️ | Play a game night where every game ends in a tie or shared first place |
| `early_bird` | Early Bird | 🐦 | Be the first person to join 10 different game nights |
| `the_rematch` | The Rematch | 🔁 | Play the same game at back-to-back consecutive game nights |
| `century_club` | Century Club | 💯 | Play in 100 total game night games across all nights |
| `dark_horse` | Dark Horse | 🐴 | Finish last in your first 3 game night games, then win one |
| `social_butterfly` | Social Butterfly | 🦋 | Play at least one game with every other registered person in the system |
| `the_oracle` | The Oracle | 🔮 | Correctly nominate the game that gets played and win it at 5 different game nights |
| `founding_member` | Founding Member | 🏛️ | Be one of the first 5 distinct Person records (by created_at) to ever appear as a Player in any game night |
| `most_wins` | Most Wins | 🥇 | Once held the record for most all-time wins across the group |

---

## Data Model

### New table: `badges`

Seeded from `BADGE_DEFINITIONS`. Not user-editable.

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

`game_night_id` is nullable — badges tied to a specific night (most of them) set it; badges that span all history (Veteran, Century Club, Social Butterfly, etc.) leave it null.

Unique constraint: `(person_id, badge_id)` — a badge can only be earned once.

### Models

Add `PersonBadge` and `Badge` to `app/models.py`. Add `person_badges` relationship to `Person`.

---

## Badge Evaluation

### Trigger

In `game_night_services.py`, inside `toggle_game_night_field`: when `field == "final"` and the new value is `True`, call `evaluate_badges_for_night(game_night_id)` from `badge_services.py`.

**Note on Retirement Party:** This badge rewards absence (not attending for 6+ months) so it can't be limited to participants. `evaluate_badges_for_night` checks this badge against *all registered `Person` records*, not just participants of the night being finalized.

### New file: `app/services/badge_services.py`

**Public API:**

```python
def evaluate_badges_for_night(game_night_id: int) -> None:
    """Evaluate all badges for all participants of the given finalized game night."""

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

A registry maps badge keys to checker functions. `evaluate_badges_for_night` iterates all participants, calls each checker, and inserts a `PersonBadge` row if the badge isn't already earned.

**Badge seeding:** A `seed_badges()` function inserts all `BADGE_DEFINITIONS` into the `badges` table (upsert by key) — called once during DB initialization / migration.

---

## Display

### User stats page (`user_stats.html`)

Add a "Badges" section at the top of the page. Shows earned badges as a grid: icon + name + earned date. Only earned badges shown — no locked/greyed-out display.

The `get_user_stats()` service function or the blueprint route enriches the template context with `badges = get_person_badges(user_id)`.

### Recap page (`recap_game_night.html`)

Add a "Badges Earned Tonight" section. Queries `PersonBadge` where `game_night_id` matches. Shows person name + icon + badge name. Section is hidden if no badges were earned that night.

`get_recap_details()` gains a `badges_earned` key: list of `{person_name, badge_name, badge_icon}` dicts.

---

## Testing

### `tests/services/test_badge_services.py` (new)

- Each checker gets at least one "earns it" and one "doesn't earn it" case.
- Complex checkers (Kingslayer, Social Butterfly, Winning Streak, The Oracle, The Closer) get edge case tests.
- `evaluate_badges_for_night` de-duplication: verify a badge isn't awarded twice if evaluation runs again.

### `tests/blueprints/test_game_night.py` (extend)

- Finalize route triggers badge evaluation and writes to `person_badges`.

### `tests/blueprints/test_stats.py` (new)

- User stats route returns badges in context.

---

## Migration

One Alembic migration: create `badges` and `person_badges` tables, then call `seed_badges()` in the `upgrade()` function.

---

## Out of Scope

- Badge notifications / alerts (beyond recap page display)
- Badge revocation
- Admin badge management UI
- Genre-based or mid-game-score-based badges (deferred)
- Eternal Bridesmaid as a badge (shown as a plain stat on the game page)

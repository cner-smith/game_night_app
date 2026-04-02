# Live Game Night Tracker — Design Spec

## Goal

An optional, per-game tracker that lets the host track scores and game state live during play. When the game ends, results flow directly into the existing game night finalization system. Manual result entry remains available if the tracker isn't used.

## Architecture

Server-side state stored in PostgreSQL. Every host action (increment counter, toggle checkbox, type a note) fires a small HTMX POST; the server updates the value and returns the refreshed HTML fragment. No client-side state — page refreshes are safe. One-screen experience: a single device (typically a shared laptop or TV) runs the tracker. Other players are not expected to interact from their own devices.

**Tech stack additions:** 4 new DB tables, 1 new blueprint, 1 new service module, 3 page templates + 2 partial templates.

**PostgreSQL 15+ required** for `NULLS NOT DISTINCT` on the `TrackerValue` unique constraint (see Data Model). The project already uses PostgreSQL 15 in Docker.

---

## Data Model

### `TrackerSession`
One per game being tracked.

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| game_night_game_id | Integer FK → GameNightGame | unique — one session per game |
| mode | String | `"individual"` or `"teams"` |
| status | String | `"active"` or `"completed"` |
| created_at | DateTime | server default |

Cascade: deleting a `TrackerSession` cascades to all `TrackerField`, `TrackerTeam`, and `TrackerValue` children. SQLAlchemy relationships must specify `cascade="all, delete-orphan"`. When a `GameNightGame` is deleted, its `TrackerSession` (if any) is deleted via the same cascade.

### `TrackerField`
The configured tracking columns for a session. Ordered by `sort_order`.

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| tracker_session_id | Integer FK → TrackerSession | cascade delete |
| type | String | `counter`, `checkbox`, `player_notes`, `global_counter`, `global_notes` |
| label | String | Host-defined name (e.g. "Victory Points", "Life", "Has Crown") |
| starting_value | Integer | For counter types only; default 0 |
| is_score_field | Boolean | True for the one counter designated for auto-ranking; default False |
| sort_order | Integer | Display order |

**Exactly one score field per session** is enforced by a partial unique index in the migration:
```sql
CREATE UNIQUE INDEX uq_one_score_field
ON tracker_fields (tracker_session_id)
WHERE is_score_field = true;
```

### `TrackerTeam`
Only exists when `mode = "teams"`.

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| tracker_session_id | Integer FK → TrackerSession | cascade delete |
| name | String | e.g. "Team A", "Red Team" |

**`tracker_team_players` join table** (team ↔ player many-to-many):

| Column | Type | Notes |
|---|---|---|
| team_id | Integer FK → TrackerTeam | cascade delete |
| player_id | Integer FK → Player | |
| PK | (team_id, player_id) | composite primary key |

Unique constraint on `(tracker_session_id, player_id)` enforced via join to `TrackerTeam` — a player may not appear in two teams in the same session. Enforced at the service layer on team assignment.

### `TrackerValue`
Live state. One row per (field, entity) pair. Entities are players (per-player fields), teams (team-level fields), or neither (global fields).

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| tracker_field_id | Integer FK → TrackerField | cascade delete |
| player_id | Integer FK → Player, nullable | null for global and team-level fields |
| team_id | Integer FK → TrackerTeam, nullable | null for individual and global fields |
| value | Text | Integer string for counters; `"true"`/`"false"` for checkboxes; free text for notes |

Unique constraint: `(tracker_field_id, player_id, team_id)` with `NULLS NOT DISTINCT` so that global fields (both NULLs) are also deduplicated. **Must be written as raw DDL in the Alembic migration** — SQLAlchemy's `UniqueConstraint` does not emit `NULLS NOT DISTINCT` by default:
```sql
ALTER TABLE tracker_values
ADD CONSTRAINT uq_tracker_value
UNIQUE NULLS NOT DISTINCT (tracker_field_id, player_id, team_id);
```

**Indexes** (include in migration):
- `tracker_values(tracker_field_id)` — hit on every HTMX value update
- `tracker_values(player_id)` — hit when loading player rows

**Type validation:** The `tracker_services` module must validate `value` on write — counter values must be castable to integer, checkbox values must be `"true"` or `"false"`. Reject invalid writes at the service layer with a `ValueError`.

---

## Field Types

| Type | Per-entity | UI | Notes |
|---|---|---|---|
| `counter` | Per player (or per team) | Number + / − buttons | Can be the score field; value may go negative (e.g. life points) |
| `checkbox` | Per player (or per team) | Toggle checkbox | |
| `player_notes` | Per player (or per team) | Text input | |
| `global_counter` | Single shared value | Number + / − buttons | Cannot be the score field |
| `global_notes` | Single shared value | Text input | |

---

## Routes

All tracker routes require `@login_required`. The live tracker GET and all write routes additionally verify the current user is a participant of the game night that owns this session (checked in `tracker_services` by joining `TrackerSession → GameNightGame → GameNight → Player`). Admins bypass the participant check.

| Method | Path | Description |
|---|---|---|
| GET | `/game_night/<gn_id>/tracker/new` | Setup page |
| POST | `/game_night/<gn_id>/tracker` | Create tracker session, redirect to live tracker |
| GET | `/tracker/<session_id>` | Live tracker page (participant or admin only) |
| POST | `/tracker/<session_id>/value` | Update a single TrackerValue (HTMX) |
| GET | `/tracker/<session_id>/end` | End-game confirmation — read-only; computes rankings but writes nothing |
| POST | `/tracker/<session_id>/save` | Save results → creates/replaces Result records, marks session completed |
| POST | `/tracker/<session_id>/discard` | Delete session and cascade children, redirect to game night |
| POST | `/tracker/<session_id>/field` | Add a field during setup (HTMX, returns field row fragment) |

### `POST /tracker/<session_id>/value` — payload

```
field_id:    int   — TrackerField.id
entity_type: str   — "player", "team", or "global"
entity_id:   int   — Player.id or TrackerTeam.id (ignored when entity_type="global")
delta:       int   — +1 or -1 for counters (omit for checkbox/notes)
value:       str   — new value for checkbox ("true"/"false") and notes fields
```

The service resolves `entity_type` + `entity_id` to the correct `player_id`/`team_id` column pair when looking up the `TrackerValue` row.

Response: the updated cell fragment HTML (see Partial Templates).

---

## Setup Flow

1. Host clicks **"Track"** next to a game on the game night page (only visible when the night is not finalized).
2. If a `TrackerSession` already exists for this game with `status = "active"`, button reads **"Resume Tracker"** — links directly to the live tracker.
3. Setup page collects:
   - **Mode:** Individual or Teams. If Teams, host names each team and assigns players to teams (service validates no player appears in two teams).
   - **Fields:** Host adds fields dynamically (see below). At least one `counter` field must be designated as the score field before the form can submit.
4. Submitting setup creates the `TrackerSession`, `TrackerField` rows, `TrackerTeam`/join rows (if teams), and seeds `TrackerValue` rows for every (field, entity) pair at `starting_value`.
5. Redirect to live tracker.

### Dynamic field-adding on setup page (HTMX)

Each "Add Field" button POSTs to `POST /tracker/<session_id>/field` with the field type, label, and starting value. The server creates the `TrackerField` row and returns a rendered field-row fragment that HTMX appends into the fields list (`hx-swap="beforeend"`). This requires the tracker session to exist before the setup page is interactive — the session is created with `status = "configuring"` on first GET of the setup page, upgraded to `"active"` on final "Launch" submit.

Field reordering on the setup page is handled client-side via SortableJS (a small drag-and-drop library). On reorder, a hidden input list of ordered field IDs is updated; the final Launch submit sends the order to the server which writes `sort_order` values.

---

## Live Tracker Page

**Layout:**
- **Global bar** (top): Rendered only if at least one `global_counter` or `global_notes` field exists; omitted entirely otherwise.
- **Player/team grid** (main): Rows are players (individual mode) or teams (teams mode). Columns are per-entity fields in `sort_order`. Score field column is visually highlighted (★).
- **Footer**: Session metadata (player count, mode, score field name) + **"End Game →"** button.

**HTMX cell fragments:**
Each cell in the grid is wrapped in a `<div id="cell-{field_id}-{entity_type}-{entity_id}">` container. The `+`/`−` buttons and the value display live inside this container. Every HTMX POST targets this container with `hx-target="#cell-{...}" hx-swap="outerHTML"`, so the entire cell (buttons + value) is replaced atomically. The value POST route renders `_tracker_cell.html` with the updated value and returns it as the fragment.

**HTMX update events:**
- Counter `+` / `−` buttons: POST with `delta=+1` or `delta=-1`
- Checkbox toggle: POST with `value="true"` or `value="false"`
- Notes fields: POST on `hx-trigger="change"` (blur). Notes do not affect results or ranking — a blur/navigation race if the host immediately clicks "End Game" is acceptable; stale notes are not a correctness issue.

**Stale sessions:** If a game night is finalized while a tracker session is `"active"`, the tracker page should detect this and redirect back to the game night with a notice. Add a guard in `GET /tracker/<session_id>` that checks `GameNight.final`.

---

## End-Game Confirmation

1. Host clicks "End Game →".
2. `GET /tracker/<session_id>/end` reads all `TrackerValue` rows for the score field (batch-loaded with the session in a single query), sorts entities descending by integer value, assigns positions 1, 2, 3…
3. Ties share a position with a gap (two players at 47 → both position 2; next is position 4).
4. Confirmation page shows: position (editable dropdown), player/team name, score field value, other counter values for reference.
5. In team mode, all members of a team inherit the team's position. Each team member's `Result` row gets the team's shared score field value as `score`.
6. Host adjusts positions if needed, hits **"Save Results →"**.
7. `POST /tracker/<session_id>/save` saves results using the existing upsert pattern from `game_night_services.log_results` (fetch-or-create per player, not DELETE + INSERT) to avoid FK issues with any tables that reference `Result`. Session `status` set to `"completed"`.
8. If `Result` rows already exist for this `GameNightGame`, a warning banner is shown on the confirmation page before save.
9. Redirect back to the game night page.

Only **position** and **score** carry over to the `Result` record. Other tracked fields are stored in `TrackerValue` for reference but do not affect badge evaluation or statistics.

---

## Integration with Existing System

- **Game night page:** Adds "Track" / "Resume Tracker" button per game. Existing manual entry is unchanged.
- **Finalization:** Tracker writes standard `Result` records — badge evaluation and recap are unaffected.
- **No migration of existing data:** Tracker is opt-in. Games without sessions use manual entry.

---

## Not In Scope

- Multi-device simultaneous editing
- Reusable tracker templates saved per game
- Tracker history, replays, or undo
- Admin cleanup UI for stale `"active"` sessions (can be handled via Flask shell if needed)

---

## New Files

| File | Purpose |
|---|---|
| `app/models.py` | Add `TrackerSession`, `TrackerField`, `TrackerTeam`, `TrackerValue` models + join table |
| `migrations/versions/<rev>_add_tracker_tables.py` | Alembic migration (raw DDL for `NULLS NOT DISTINCT` and partial unique index) |
| `app/blueprints/tracker.py` | All tracker routes |
| `app/services/tracker_services.py` | Business logic: create session, update value, validate types, compute rankings, save results |
| `app/templates/tracker_setup.html` | Setup page (includes SortableJS via CDN) |
| `app/templates/tracker_live.html` | Live tracker page |
| `app/templates/tracker_confirm.html` | End-game confirmation |
| `app/templates/_tracker_cell.html` | Partial: single cell fragment returned by value POST (counter, checkbox, or notes) |
| `app/templates/_tracker_field_row.html` | Partial: single field row returned by setup field-add POST |
| `app/templates/view_game_night.html` | Add Track/Resume Tracker buttons per game |
| `tests/blueprints/test_tracker.py` | Blueprint integration tests |
| `tests/services/test_tracker_services.py` | Service unit tests |

---

## Testing

**Service tests** (`test_tracker_services.py`):
- Creating a session seeds correct `TrackerValue` rows at starting values for all (field, entity) pairs
- Updating a counter increments/decrements correctly; values may go negative
- Invalid value type (non-integer for counter, non-boolean for checkbox) raises `ValueError`
- Auto-ranking sorts descending by score field value; loads all values in one query (no N+1)
- Ties assign shared position with correct gap (two 2nds → next is 4th)
- `save_results` creates `Result` rows with correct `position` and `score`
- `save_results` uses upsert — does not create duplicate rows if Results already exist
- Team mode: all team members get the team's position and the team's score value
- Discard cascades — all TrackerField, TrackerValue, TrackerTeam rows are deleted

**Blueprint tests** (`test_tracker.py`):
- Setup POST creates session and redirects to live tracker
- Field-add POST returns a field row fragment and creates the TrackerField row
- Value POST updates the correct `TrackerValue` row and returns the cell fragment
- End-game GET returns auto-ranked results without writing anything
- Save POST creates `Result` records and marks session completed
- Non-participant GET of live tracker is rejected (403 or redirect)
- Unauthenticated requests are redirected to login

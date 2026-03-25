# Gamenight App — Redesign & Feature Expansion

**Date:** 2026-03-25
**Repo:** https://github.com/cner-smith/game_night_app
**Context:** Personal board game night coordination app for a small friend group. Hosted on a home lab via Docker. Not commercial. Mobile-friendly is a hard requirement.

---

## Goals

1. Modernize the UI/UX — currently bland custom CSS, replace with Tailwind CSS and a new navigation structure
2. Complete BGG (BoardGameGeek) API integration — live game search and richer game detail pages
3. Add a poll/availability system — shareable links for scheduling questions, no login required to respond
4. Improve code quality — add a test suite (pytest), clean up patterns, write proper documentation

---

## Architecture

### What stays

- Flask + SQLAlchemy + PostgreSQL
- Flask-Login, Flask-Mail, APScheduler
- Jinja2 templates (server-rendered)
- Docker / Docker Compose for deployment
- Existing blueprint/services structure (`app/blueprints/`, `app/services/`)
- All existing data models (no schema changes in Phases 1–2)

### What changes

- **Tailwind CSS** (via CDN) replaces `app/static/css/styles.css`. No Node.js build step required at this scale.
- **HTMX** (via CDN) added to base template. Used for live BGG search, vote submission, and poll responses — no full page reloads for these interactions.
- `pytest` + `pytest-flask` added for the test suite. Tests live in `tests/`.
- A `BGGService` class introduced in `app/services/bgg_service.py`, wrapping the existing `fetch_and_parse_bgg_data` utility and adding search support.
- `Poll` and `PollOption` and `PollResponse` models added in Phase 3 (new tables, migration required).

### What does not change

- Auth flow and session handling
- All existing service logic
- Deployment infrastructure
- Database schema (until Phase 3 poll tables)

---

## Phase 1: UI Overhaul

**Goal:** Replace the custom CSS with Tailwind. Redesign every template with the new visual style and navigation. No behavior changes — the app works identically, just looks much better.

### Visual style

- **Theme:** Clean & light — white/warm-white background (`stone-50`), red accent (`red-600`), warm gray text (`stone-700`)
- **Typography:** System font stack via Tailwind defaults
- **Cards, shadows, rounded corners** throughout — Tailwind utility classes

### Navigation

- **Desktop:** Collapsible icon sidebar (left side). Icons with tooltip labels on hover. Sections: Home, Games, Wishlist, Stats, Admin (conditional), User/Sign Out at bottom.
- **Mobile:** Top bar with app name/logo only. Fixed bottom tab bar with 4–5 icon+label tabs: Home, Games, Stats, Me (profile/logout). Admin tab appears conditionally.
- Tailwind's responsive prefix (`md:`) handles the desktop/mobile split.

### Templates to update

All templates inherit from `base.html`. Updating `base.html` (nav structure, Tailwind link) and the shared CSS file handles the shell. Each content template then gets Tailwind class replacements:

- `base.html`, `auth_base.html` — nav, layout shell
- `index.html` — home/dashboard
- `games_index.html`, `view_game.html`, `add_game.html` — game library
- `add_to_wishlist.html`, `wishlist.html` — wishlist
- `user_stats.html` — stats
- `start_game_night.html`, `view_game_night.html`, `all_game_nights.html`, `edit_game_night.html`, `add_game_to_night.html`, `nominate_game.html`, `log_results.html` — game night flow
- `admin_page.html`, `add_person.html`, `manage_user.html` — admin
- `login.html`, `signup.html`, `forgot_password.html`, `update_password.html` — auth pages
- Email templates updated to match new style

### Testing for Phase 1

No new business logic — no new unit tests required. Smoke tests are sufficient: parameterized route checks via the Flask test client verifying each page returns 200 (or expected redirect) without a 500 error.

---

## Phase 2: BGG API Integration

**Goal:** Replace manual game entry with a live BGG search flow, and enrich game detail pages with BGG data.

### Search-to-add flow

The existing `add_game.html` form currently takes a name and optional BGG ID. This is replaced with:

1. User types a game name into a search field
2. HTMX fires a request to a new endpoint `GET /games/bgg-search?q=<query>` on each keystroke (debounced ~400ms)
3. Flask calls the BGG XML search API, returns a partial HTML template (`_bgg_results.html`) listing matching games with thumbnail, name, year
4. User clicks a result — this populates a hidden `bgg_id` field and confirms their selection
5. User submits — existing `add_game` logic handles the rest (already calls `get_or_create_game` with `bgg_id`)

**BGGService** (`app/services/bgg_service.py`):
- `search(query: str) -> list[dict]` — calls BGG XML API search endpoint, parses results
- `fetch_details(bgg_id: int) -> dict` — existing `fetch_and_parse_bgg_data` wrapped here
- BGG XML API is public (no auth key required for search and item lookup)
- Responses cached in-memory (simple dict cache with TTL) to avoid hammering BGG on repeated searches

### Richer game detail pages

`view_game.html` is extended to show (when available):

- BGG rating and rank
- Complexity score (weight)
- Categories and mechanics tags
- "How to play" link (already stored as `tutorial_url`)
- Min/max players and playtime (already in model, just better displayed)

BGG data that doesn't already exist in the model (rating, complexity, categories) is display-only and not stored in the database — no new model fields required. On `view_game` page load, the `BGGService` is called and the result is served from the in-memory cache if available (same cache used by search, 10-minute TTL). On a cache miss the BGG API is called and the result is cached. This means the first load after cache expiry makes a live call; subsequent loads within the TTL window are instant. This is consistent with the in-memory cache described in the search flow above.

### Testing for Phase 2

- Unit tests for `BGGService.search()` and `BGGService.fetch_details()` using mocked HTTP responses (`unittest.mock` or `pytest-mock`)
- Integration test for `/games/bgg-search` endpoint — mock BGG API, verify HTML fragment returned
- Test for `get_or_create_game` with and without `bgg_id` (existing logic, adding test coverage)

---

## Phase 3: Poll / Availability System

**Goal:** Allow the admin to create polls (most commonly scheduling/availability polls), share them via a link, and collect responses without requiring login.

### Data model (new tables)

```
Poll
  id              integer PK
  title           text NOT NULL
  description     text
  created_by      integer FK → people.id
  created_at      datetime
  closes_at       datetime (nullable — open-ended polls)
  closed          boolean default false
  token           text UNIQUE NOT NULL  -- generated via secrets.token_urlsafe(16), used in shareable URL
  multi_select    boolean default false -- true = checkboxes, false = radio buttons

PollOption
  id              integer PK
  poll_id         integer FK → polls.id
  label           text NOT NULL
  display_order   integer

PollResponse
  id              integer PK
  poll_id         integer FK → polls.id
  option_id       integer FK → polloptions.id
  person_id       integer FK → people.id (nullable — anonymous responses)
  respondent_name text (used when person_id is null)
  created_at      datetime
  -- One row per selected option. For single-select polls this is always one row
  -- per respondent. For multi-select it can be multiple rows per respondent.
```

### Flows

**Admin creates a poll:**
- New admin panel section: "Polls"
- Form: title, description, list of options (dynamic add/remove via HTMX), optional close date
- On submit: poll is created, shareable URL generated as `/poll/<token>`

**Sharing:**
- Admin copies the URL from the admin panel
- Can also trigger an email to all registered users via existing Flask-Mail setup

**Responding (no login required):**
- `/poll/<token>` renders the poll publicly
- Respondent selects options (single or multiple depending on poll type) and enters their name if not logged in
- HTMX submits response, page updates to show "thanks" state and current results
- Duplicate prevention: enforced at the application layer (not a DB UNIQUE constraint). For single-select polls, submitting checks whether any `PollResponse` rows already exist for `(poll_id, person_id)` / `(poll_id, respondent_name)` and rejects re-submission. For multi-select polls, the entire previous response set for the respondent is deleted and replaced on re-submission (last write wins). This is intentionally lightweight — suitable for a trust-based friend group.
- Results visibility: a respondent must submit a response before they can see results. Anyone who has responded (logged-in or anonymous) can then see live results at any time by revisiting the poll URL. The admin can always see full results from the admin panel regardless of whether they've responded.

**Results view:**
- Logged-in users and anyone with the link can see live results after responding
- Admin sees full results in admin panel including respondent names

**On-site surfacing:**
- Active polls shown on the home/dashboard page for logged-in users
- Link in nav for logged-in users if any active polls exist

### Testing for Phase 3

- Unit tests for poll creation service
- Unit tests for response submission (duplicate prevention, anonymous vs. logged-in)
- Integration tests for `/poll/<token>` route — valid token, expired poll, already responded
- Test for shareable URL generation (token uniqueness)

---

## Testing Strategy

- **Framework:** `pytest` + `pytest-flask`
- **Test location:** `tests/` at repo root, mirroring app structure (`tests/services/`, `tests/blueprints/`)
- **Scope:** Unit tests for service functions; integration tests for Flask routes using the test client; no browser/E2E tests (overkill for this project)
- **Database:** Tests use a separate in-memory SQLite database or a test PostgreSQL database (configured via `TEST_DATABASE_URL` env var)
- **Mocking:** BGG API calls are always mocked in tests — no real network calls
- **CI:** GitHub Actions runs on every push and pull request — see CI/CD section below

---

## Documentation

- **README.md** — rewritten to cover: what the app does, local dev setup, environment variables, Docker deployment, how to run tests, how to add games
- **`docs/`** — inline comments added to any new or significantly changed service functions
- **CHANGELOG.md** — created to document what changed in this overhaul, for handoff back to the original author
- `.gitignore` updated to include `.superpowers/`

---

## CI/CD & Automation

### CI (GitHub Actions — unconditional)

A `.github/workflows/ci.yml` workflow runs on every push and pull request to `main`:

1. **Lint & format check** — `ruff check` and `ruff format --check`. Ruff replaces flake8, black, and isort in a single fast tool. Config lives in `pyproject.toml`.
2. **Type checking** — `mypy` on `app/` and `tests/`. Catches type errors statically. Config in `pyproject.toml`.
3. **Security scan** — `bandit -r app/` flags common Python security issues (SQLi, hardcoded secrets, etc.).
4. **Tests** — `pytest` with coverage report. Uses a test PostgreSQL service container in the Actions environment (matches production DB engine).

All four steps must pass for a push to be considered clean. The workflow uses Python 3.11 and caches pip dependencies.

**New dev dependencies added to `requirements-dev.txt`:** `ruff`, `mypy`, `bandit`, `pytest`, `pytest-flask`, `pytest-cov`, `pytest-mock`

A `.pre-commit-config.yaml` is also added so the same ruff and mypy checks can run locally before push (opt-in via `pre-commit install`).

### CD (auto-deploy to homelab — TBD)

> **Pending:** Waiting to confirm how the homelab receives updates (SSH access, self-hosted Actions runner, Watchtower, etc.) before specifying the deployment pipeline. This section will be completed before implementation planning begins.
>
> Options under consideration:
> - **Self-hosted GitHub Actions runner** on the homelab — runner pulls the repo and runs `docker compose up --build -d` on successful CI. No inbound port exposure needed.
> - **Watchtower** — watches Docker Hub for a new image pushed by CI, auto-redeploys. Requires a Docker Hub push step in CI.
> - **Scripted manual deploy** — CI passes, developer SSHs in and runs `./scripts/deploy.sh`. Simpler, still documented and reproducible.

---

## Constraints & Non-Goals

- No commercial deployment, no scalability requirements
- No real-time features (WebSockets, live vote updates) — HTMX polling is sufficient if ever needed
- No mobile app — responsive web only
- BGG API is public XML API — no auth token required for search/item lookup (the existing `fetch_and_parse_bgg_data` utility confirms this pattern)
- Poll system does not need email verification or CAPTCHA — trust-based for a friend group

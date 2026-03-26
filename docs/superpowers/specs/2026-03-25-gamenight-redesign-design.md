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
- **Flask-Migrate (Alembic)** added in Phase 1 alongside the test suite. Required for Phase 3 schema additions; set up early so all phases can be tracked via migrations from the start.
- **BGGService** (`app/services/bgg_service.py`) — new service class containing all BGG HTTP and XML parsing logic. The existing fragile import chain (`games_services.py` → `utils.py` → top-level `fetch_bgg_data.py`) is deleted and replaced. `fetch_bgg_data.py` (both the root-level copy and `scripts/` copy) are removed.
- **Polls blueprint** — new `app/blueprints/polls.py` handles all poll routes (admin-gated management routes and the public `/poll/<token>` endpoint). Poll logic is not added to `admin.py`.
- `Poll`, `PollOption`, and `PollResponse` models added in Phase 3 (new tables, Alembic migration required).
- **Gunicorn worker count** fixed to 1 (`-w 1`) in the production Docker Compose command. The in-memory BGGService cache and APScheduler are per-process; multiple workers would cause cache thrashing and duplicate scheduled job execution. Single worker is appropriate for homelab scale.
- **Docker housekeeping** done alongside Phase 1: add `.dockerignore`, fix Dockerfile layer order (copy requirements before app code), remove host-bind volume mounts for templates/static from production compose (app must use files baked into the image), add compose healthcheck.

### What does not change

- Auth flow and session handling
- Deployment infrastructure (Docker Compose, Traefik, homelab setup)
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

### Phase 1 infrastructure tasks (alongside UI work)

These have no user-visible effect but must be done in Phase 1 so subsequent phases build on solid ground:

- **Set up Flask-Migrate** — initialise Alembic, create an initial migration from the current schema (`flask db init`, `flask db migrate`, `flask db upgrade`). All future schema changes use `flask db migrate` rather than `db.create_all()`.
- **Remove `test_bp`** — the debug blueprint registered unconditionally in `app/__init__.py` should be deleted or gated behind `app.debug`.
- **Dockerfile housekeeping** — fix layer order, add `.dockerignore`, pin Python to `3.11-slim`, remove host-bind volume mounts for templates/static from production compose, add healthcheck, set `gunicorn -w 1`.
- **Set up test infrastructure** — `tests/` directory, `conftest.py`, pytest + pytest-flask configured against a test PostgreSQL database via `TEST_DATABASE_URL`.

### Testing for Phase 1

No new business logic — no new unit tests required. Smoke tests are sufficient: parameterized route checks via the Flask test client verifying each page returns 200 (or expected redirect) without a 500 error. **These smoke tests must be committed and green before Phase 2 begins** — they serve as the regression harness for template changes made during Phase 2.

---

## Phase 2: BGG API Integration

**Goal:** Replace manual game entry with a live BGG search flow, and enrich game detail pages with BGG data.

### Search-to-add flow

The existing `add_game.html` form currently takes a name and optional BGG ID. This is replaced with:

1. User types a game name into a search field
2. HTMX fires a request to a new endpoint `GET /games/bgg-search?q=<query>` on each keystroke (debounced ~400ms)
3. Flask calls the BGG XML search API, returns a partial HTML template (`_bgg_results.html`) listing matching games with thumbnail, name, year. If BGG is unavailable or times out, the fragment renders a single error line ("Could not reach BoardGameGeek — please try again").
4. User clicks a result — HTMX swaps the entire search widget with a "selected game" confirmation div. The confirmation div contains the game name, thumbnail, and a hidden `<input name="bgg_id">` with the selected BGG ID baked in. A "change" link re-renders the search widget.
5. User submits — existing `add_game` logic handles the rest (already calls `get_or_create_game` with `bgg_id`)

**BGGService** (`app/services/bgg_service.py`):
- `search(query: str) -> list[dict]` — calls BGG XML API search endpoint, parses results. Returns empty list if `len(query) < 3` (server-side guard, no API call made).
- `fetch_details(bgg_id: int) -> dict` — all BGG HTTP and XML parsing logic lives here. The existing `fetch_bgg_data.py` is deleted; no wrapper chain.
- BGG XML API is public (no auth key required for search and item lookup)
- **All `requests.get()` calls use an explicit timeout of 5 seconds.** A BGG outage must not hang a gunicorn worker.
- **BGG 202 handling:** BGG's XML API2 sometimes returns `HTTP 202` with an empty body on first lookup (it is still generating the response). `fetch_details` must retry once after a 1-second delay on 202. If the retry also returns 202, return an empty dict gracefully.
- Responses cached using `cachetools.TTLCache` (max 200 entries, 10-minute TTL) — bounded memory, correct eviction. `cachetools` added to `requirements.txt`.
- `TTLCache` requires an explicit lock for thread safety: `cachetools.cached(cache=TTLCache(...), lock=threading.RLock())`. APScheduler runs in a background thread even with a single gunicorn worker, so the cache can be accessed concurrently.
- Cache is per-process (intentional given single gunicorn worker — see Architecture).

### Richer game detail pages

`view_game.html` is extended to show (when available):

- BGG rating and rank
- Complexity score (weight)
- Categories and mechanics tags
- "How to play" link (already stored as `tutorial_url`)
- Min/max players and playtime (already in model, just better displayed)

BGG data that doesn't already exist in the model (rating, complexity, categories) is display-only and not stored in the database — no new model fields required. BGG enrichment data loads via a **secondary HTMX request** after the core page renders. The `view_game.html` page loads instantly from the database; an `hx-get="/games/<id>/bgg-details"` fires immediately on page load to fill in the BGG metadata panel. This prevents a cold-cache BGG API call from blocking the entire page render. The BGG details endpoint returns a small HTML fragment; on error or timeout it returns a graceful "BGG data unavailable" fragment.

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
- `respondent_name` is stored as entered (preserving original casing for display in results), but normalised (`strip().lower()`) for duplicate-prevention lookups only. The `PollResponse` table stores the original value; all duplicate checks normalise before comparing.
- Duplicate prevention: enforced at the application layer. `respondent_name` matching uses the normalised value. For single-select polls, submitting checks whether any `PollResponse` rows already exist for `(poll_id, person_id)` / `(poll_id, respondent_name)` and rejects re-submission. For multi-select polls, the entire previous response set for the respondent is deleted and replaced on re-submission (last write wins). Known limitation: two different people with the same name cannot both respond anonymously — acceptable for a friend group.
- **Anonymous results visibility:** On successful submission, a session cookie (`poll_<token>_responded = true`) is set. On revisiting `/poll/<token>`, the app checks this cookie to decide whether to show the results view or the response form. Logged-in users are checked via `PollResponse` query against their `person_id`. The admin always sees results regardless.
- **Poll token collision:** On the (astronomically unlikely) event of a `UNIQUE` constraint violation during poll creation, the service retries token generation up to 3 times before raising an error.
- **`poll_is_active(poll)` helper:** A single service-layer function checks both closure mechanisms: `return not poll.closed and (poll.closes_at is None or poll.closes_at > datetime.utcnow())`. All routes and templates use this helper — never check `closed` or `closes_at` directly.

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
- **Database:** Tests require a PostgreSQL database (configured via `TEST_DATABASE_URL` env var). SQLite is not supported — existing models use `db.ARRAY` (PostgreSQL-only) and several SQL views that require PostgreSQL DDL. In CI this is a service container; locally developers run a PostgreSQL instance (documented in README).
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
2. **Type checking** — `mypy` on `app/` and `tests/`. Config in `pyproject.toml` with `ignore_missing_imports = true` — several Flask extensions (`flask-login`, `flask-mail`, `flask-bcrypt`, `apscheduler`) do not ship type stubs; this prevents mypy from failing on day one due to unresolvable imports rather than real type errors.
3. **Security scan** — `bandit -r app/ -ll -ii` (medium+ severity, medium+ confidence). The threshold flags are required to suppress low-signal noise; without them bandit becomes something developers learn to ignore.
4. **Docker build check** — `docker build .` verifies the image builds cleanly. Cheap, catches dependency installation failures and Dockerfile errors before they reach the homelab.
5. **Tests** — `pytest --cov=app --cov-fail-under=60` with a PostgreSQL service container. The 60% threshold is a floor to prevent coverage from drifting to zero; it can be raised as the test suite grows.

All five steps must pass for a push to be considered clean. The workflow uses **Python 3.11** and caches pip dependencies (cache key hashes both `requirements.txt` and `requirements-dev.txt`). **The Dockerfile is updated to use `python:3.11-slim`** to match.

**New dev dependencies added to `requirements-dev.txt`:** `ruff`, `mypy`, `bandit`, `pytest`, `pytest-flask`, `pytest-cov`, `pytest-mock`, `pre-commit`

**New runtime dependency added to `requirements.txt`:** `cachetools`

A `.pre-commit-config.yaml` is also added so the same ruff and mypy checks can run locally before push (opt-in via `pre-commit install`). The `.pre-commit-config.yaml` pins the same ruff version as `requirements-dev.txt` to prevent silent divergence.

### CD (auto-deploy to homelab)

The homelab already has a GitHub webhook configured: on every push to `main`, it restarts the Docker container and pulls the latest image. This existing mechanism is preserved and extended rather than replaced.

**How it works after this project:**

1. **Image publishing** — A `publish` job in `.github/workflows/ci.yml` runs only after the `ci` job passes on `main`. It builds the Docker image and pushes it to GitHub Container Registry (`ghcr.io/<owner>/game_night_app:latest`). Images are only published for CI-passing commits — a failing push never produces a new image.

2. **Homelab webhook** — The existing webhook continues to fire on push, pulling from GHCR and restarting the container. Because the image is only published after CI passes, the homelab will always be running a vetted build. In the (brief) window between the push event and GHCR publish completing, the webhook restarts with the previous image — this is safe and self-correcting.

3. **Migrations** — A `scripts/entrypoint.sh` script is added to the repo and set as the Docker `ENTRYPOINT`. On every container start it runs `flask db upgrade` before handing off to gunicorn. Alembic migrations are idempotent: if no migration is pending, the command is a no-op. This ensures Phase 3 schema changes are applied automatically on deploy without any changes to the homelab webhook script.

**Rollback:** Re-push a previous commit to `main`. CI runs and publishes the old image; the webhook restarts with it. For database rollbacks, run `flask db downgrade` manually on the homelab — this is intentionally manual given the homelab scale.

**GHCR authentication:** The `publish` job uses `GITHUB_TOKEN` (automatically available in Actions) for `docker login`. No additional secrets are required.

---

## Constraints & Non-Goals

- No commercial deployment, no scalability requirements
- No real-time features (WebSockets, live vote updates) — HTMX polling is sufficient if ever needed
- No mobile app — responsive web only
- BGG API is public XML API — no auth token required for search/item lookup (the existing `fetch_and_parse_bgg_data` utility confirms this pattern)
- Poll system does not need email verification or CAPTCHA — trust-based for a friend group

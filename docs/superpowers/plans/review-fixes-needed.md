# Plan Review — Fixes Needed
> Generated 2026-03-25. Apply phase by phase. Delete this file when all fixes committed.

---

## PHASE 1 fixes (`2026-03-25-phase1-ui-infrastructure.md`)

### Critical blockers
- [ ] **Task 2, Step 3** — Add brownfield decision branch: if DB already has tables, run `flask db stamp head` instead of `flask db upgrade`. Add note about SQL view models: after `flask db migrate`, agent must inspect generated migration and verify only real table DDL is present (view-backed models `GamesIndex`, `UserRecentFutureGameNight`, etc. must not appear as `CREATE TABLE`). Add `alembic_exclude_tables` or manual review step.
- [ ] **Task 3, Step 3** — Add `ENV FLASK_APP=app` to the Dockerfile template (entrypoint.sh needs this for `flask db upgrade`).
- [ ] **Task 4, Step 2** — Fix `auth_client`/`admin_client` fixtures: login posts to `/login` not `/auth/login` (auth_bp has no url_prefix). Fix `SESSION_TYPE`: replace `os.environ["SESSION_TYPE"] = "null"` with `app.config["SESSION_TYPE"] = "null"` set after `create_app()`. Remove `SERVER_NAME="localhost"` from `app.config.update` — breaks `url_for`.
- [ ] **Task 4, Step 3** — Fix ALL route paths in smoke tests. AUTH_ROUTES: `/login`, `/signup`, `/forgot_password` (not `/auth/...`). REDIRECT_ROUTES: check actual blueprint routes — `/wishlist` not `/games/wishlist`, `/user_stats` not `/games/stats`. Add `flask routes` verification step.
- [ ] **Task 6, Step 2** — Fix missing `{% endif %}` before `</aside>` in base.html. Fix both `{% if current_user.admin or current_user.owner %}` occurrences (desktop sidebar + mobile nav) to guard with `{% if current_user.is_authenticated and (...) %}`.

### High severity
- [ ] **Task 2, Step 2** — Add step to also remove `from .test import test_bp` from `app/blueprints/__init__.py` (plan removes registration but not import; ruff flags unused import).
- [ ] **Task 2, Step 3** — Add prerequisite: `export FLASK_APP=app` before `flask db init/migrate/upgrade`.
- [ ] **Task 3, Step 2** — Add "Read the existing `scripts/entrypoint.sh` first" step — file already exists (cron daemon + `-w 4`). Determine if cron jobs are dead code (APScheduler replaces them) before overwriting.
- [ ] **Task 4, Step 2** — Add monkeypatch to disable APScheduler in tests: mock `start_schedulers` or set `TESTING=1` env var and check it in `start_schedulers`. Otherwise background thread fires during test teardown.
- [ ] **Task 4, Step 3** — Expand smoke tests to cover game night routes. Add a minimal DB seed fixture (one Game, one Person, one GameNight) so routes with path params can be tested. Aim for coverage of all GET routes that render templates.
- [ ] **Task 5, Step 1** — Add note: homelab webhook must be updated to `docker pull ghcr.io/cner-smith/game_night_app:latest` — "existing webhook continues to work" is a handwave if it currently builds locally.
- [ ] **Task 5, Step 1** — Change `mypy app/` to `mypy app/ tests/`.
- [ ] **Task 6, Step 2** — Add step to create placeholder files in `app/static/images/`: `favicon.svg`, `favicon.ico`, `apple-touch-icon.png`, `site.webmanifest`, `logo.png`. Without them every page load gets 404s and the sidebar logo is broken.
- [ ] **Tasks 7–9** — Every template update task needs: (1) explicit "Read the current file first" step, (2) brief description of the layout/context variables available (from the route), (3) remove "Apply same Tailwind patterns" handwave and replace with concrete instructions.
- [ ] **Task 10, Step 3** — Create `.env.example` step. Fix README Deployment section: remove manual `flask db upgrade` instruction (entrypoint handles it now).

### Medium/Low
- [ ] **Task 1, Step 2** — Change version pins to `>=` lower bounds or add note to verify latest at execution time.
- [ ] **Task 1** — Add note that a virtualenv is assumed active (or add `python -m venv .venv && source .venv/bin/activate`).
- [ ] **Task 2, Step 2** — Remove `db.create_all()` from `setup_database` entirely (Flask-Migrate is now the migration mechanism; conftest handles test schema creation).
- [ ] **Task 5, Step 1** — Note `postgres:15` pin; add comment matching homelab Postgres version.
- [ ] **Task 9, Steps 2 & 5** — Remove stray `**` markdown artifacts from step text.
- [ ] **All** — Add `.gitignore` update step: add `.superpowers/`, `flask_session/`, `.env`, `*.pyc` if not already present.

---

## PHASE 2 fixes (`2026-03-25-phase2-bgg-integration.md`)

### Critical blockers
- [ ] **Task 1** — Add step to add `cachetools` to `requirements.txt` (not just requirements-dev.txt — it's a runtime dependency). App fails at import without it.
- [ ] **Task 2, Step 1** — Add step to also update `app/utils/__init__.py`: remove `fetch_and_parse_bgg_data` from its import/export list. Without this, `from app.utils import fetch_and_parse_bgg_data` in other files still resolves (to a deleted function) causing ImportError.
- [ ] **Task 3, Step 3** — Move `from app.services.bgg_service import BGGService` to TOP of `games.py` imports (not mid-file — ruff E402 fails CI). Also add `from app.models import Game` to imports (Game not currently imported in games.py; route uses `Game.query.get_or_404`).
- [ ] **Task 3, Step 4 (`_bgg_results.html`)** — Replace `| urlencode` filter on individual strings with `url_for('games.bgg_search', select=game.bgg_id, name=game.name, year=game.year, thumbnail=game.thumbnail)`. Jinja2's `urlencode` encodes dicts, not strings — will raise TemplateRuntimeError.
- [ ] **Task 3, Step 6 (`_bgg_selected.html`)** — Fix "Change" button: it sends `hx-get="...?q="` (empty query) which returns empty string, destroying `#bgg-search-widget` with nothing. Button should swap in a blank widget div that preserves the `id="bgg-search-widget"` target. Create `_bgg_empty_widget.html` fragment or have the route return a blank widget on empty `q`.

### High severity
- [ ] **Task 1, Step 3** — Fix `fetch_details` to not cache `{}` (error result). Add guard: `if result: _cache[bgg_id] = result`. Otherwise a BGG timeout poisons the cache for 10 min.
- [ ] **Task 1, Step 1 (`SEARCH_XML` fixture)** — Note that BGG search API does NOT return `<thumbnail>` in search results. Remove `thumbnail` from `SEARCH_XML` and from the `_parse_search` return dict, or add explicit comment that it will always be empty string in production.
- [ ] **Task 3, Step 1 (`test_bgg_details_fragment_returns_html`)** — Wrap test in try/finally for DB cleanup. Game creation should be in a fixture not inline in test body.
- [ ] **Task 3, Step 5** — Rewrite Task 4, Step 2 to be concrete verification steps instead of "verify it works".
- [ ] **Task 2, Step 5** — Replace "fix any import errors" with specific guidance: if `ImportError: cannot import name 'fetch_and_parse_bgg_data'`, check `app/utils/__init__.py`.

### Medium/Low
- [ ] **Task 1, Step 3** — Extract `time.sleep(1)` to `_RETRY_DELAY = 1` constant. Add `patch("app.services.bgg_service._RETRY_DELAY", 0)` to retry test so it doesn't slow CI by 1s.
- [ ] **Task 1** — Add test for `BGGService.search()` on `ConnectionError` and 500 response.
- [ ] **Task 1** — Add explicit note: "This implementation deliberately uses manual `with _lock:` guards instead of `@cachetools.cached` decorator. Do NOT switch to decorator pattern — it breaks the `_bgg_module._cache.clear()` test fixture."
- [ ] **Task 2, Step 3** — Replace "replace all calls" handwave with full rewritten `get_or_create_game` showing both call sites updated.

---

## PHASE 3 fixes (`2026-03-25-phase3-poll-system.md`)

### Critical blockers
- [ ] **Task 2, Step 1 + Task 3, Step 1 (`poll_author` fixtures)** — `Person(name=...)` fails — real model uses `first_name` and `last_name` (NOT NULL), not `name`. Fix both fixtures. Also use random email suffix to avoid unique constraint collisions across test runs: `email=f"author_{uuid.uuid4().hex[:8]}@test.invalid"`.
- [ ] **Task 3, Step 1 (`poll_author` fixture teardown)** — Fixture deletes Person while Poll rows (with `created_by` NOT NULL FK) still exist → FK violation. Remove manual delete; rely on `db` fixture's global teardown instead.
- [ ] **Task 4, Step 2** — Add `poll_option_row` route to blueprint in Task 3, Step 3. The template `poll_create.html` calls `url_for('polls.poll_option_row')` but this route is never added to `polls.py` — raises `BuildError` at runtime.
- [ ] **Task 3, Step 3** — Replace `# Adjust import to match existing decorator path` comment with the exact correct import: `from app.utils import admin_required` (confirmed path from reading `admin.py`).

### High severity
- [ ] **Task 3, Step 1** — Add complete fallback implementation for `admin_client` and `auth_client` fixtures in case they're missing from Phase 1 conftest. Show the Person model fields required (`first_name`, `last_name`, `admin=True` for admin user) and the correct login URL (`/login`).
- [ ] **Task 3, Step 5** — Replace "fix any issues" handwave with specific checklist: (a) ImportError on admin_required → use `from app.utils import admin_required`; (b) 404 on `/polls/create` → verify blueprint registered; (c) 302 on admin POST → check admin fixture has `admin=True`.
- [ ] **Task 5, Step 1** — Fix nav item behavior: nav link to `polls.poll_list` is admin-only. Regular users clicking it get silently redirected. Either show the nav link only to admins (`{% if current_user.is_authenticated and (current_user.admin or current_user.owner) %}`), or create a public-facing polls landing page.
- [ ] **Task 5, Step 2** — Provide complete updated context processor code injecting both `active_polls_count` and `active_polls` list.
- [ ] **Task 5, Step 3** — Provide exact HTML snippet and insertion point for admin page polls link.

### Medium/Low
- [ ] **Task 2, Step 1** — Add test for `poll_is_active` at exact `closes_at` boundary (`closes_at = datetime.utcnow()`).
- [ ] **Task 2, Step 1** — Add test for multi-select replacement with logged-in user (`person_id` not None).
- [ ] **Task 2, Step 1** — Add test for token collision: mock `Poll.generate_token` to return constant, pre-insert poll with that token, assert `RuntimeError` raised.
- [ ] **Task 3** — Add test: `test_admin_poll_list_shows_polls(admin_client, open_poll)`.
- [ ] **Task 3** — Add test: `test_submit_response_rejects_missing_name` (no `respondent_name` in POST).
- [ ] **Task 4, Step 4** — Add assertions to `test_poll_page_loads`: `assert b'name="option_ids"' in resp.data` and `assert b'name="respondent_name"' in resp.data`.
- [ ] **Task 4** — Note HTMX/Tailwind CDN requires internet access during UI testing; add skip condition for offline environments.
- [ ] **Task 6, Step 4** — Mark deploy step as `[HUMAN ACTION REQUIRED]` — AI agent should not attempt to SSH into homelab.
- [ ] **Task 4, Step 6** — Always pass `results=None` in error-path renders of `_poll_thanks.html`.
- [ ] **Task 3, Step 1** — Move `poll_author` fixture to shared `tests/conftest.py` (currently defined twice in separate test files — unique email collisions across runs).

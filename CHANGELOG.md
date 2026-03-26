# Changelog

All notable changes to this project will be documented here.

## [Unreleased]

### Added
- Tailwind CSS CDN replacing custom CSS
- HTMX CDN (used in Phase 2 BGG integration)
- Icon-only sidebar navigation (desktop) + mobile bottom tab bar
- Flask-Migrate (Alembic) for database schema management
- pytest infrastructure with PostgreSQL-backed integration tests
- GitHub Actions CI pipeline (lint → typecheck → security → build → test → publish)
- `.env.example` for new developer onboarding
- `.dockerignore` for cleaner Docker builds
- Python 3.11 base image in Dockerfile

### Changed
- Dockerfile upgraded from Python 3.10 to 3.11 with optimized layer caching
- `entrypoint.sh` now runs `flask db upgrade` before starting gunicorn
- Removed unconditional `test_bp` blueprint registration
- Removed `db.create_all()` call (replaced by Flask-Migrate)
- Gunicorn reduced to `-w 1` (APScheduler is per-process)

### Removed
- `app/static/css/styles.css` bulk custom CSS (kept only minimal overrides)

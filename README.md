# game_night_app

A Flask web app for coordinating board game nights with friends — track your library, schedule game nights, record results, and run polls.

## Stack

- Python 3.11 + Flask 2.3
- PostgreSQL + SQLAlchemy + Flask-Migrate (Alembic)
- Tailwind CSS (CDN) + HTMX (CDN)
- Gunicorn + Docker + GitHub Actions CI

## Local Development

### Prerequisites
- Python 3.11+
- PostgreSQL running locally
- Docker (optional, for container testing)

### Setup

```bash
# Clone the repo
git clone https://github.com/Gammill32/game_night_app
cd game_night_app

# Create and activate virtualenv
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL and SECRET_KEY at minimum

# Initialize database migrations
export FLASK_APP=app
flask db init          # first time only
flask db stamp head    # if existing schema (brownfield)
flask db upgrade       # apply migrations

# Run the dev server
flask run
```

### Running Tests

```bash
export TEST_DATABASE_URL=postgresql://user:password@localhost:5432/gamenight_test
pytest
```

### Linting

```bash
ruff check .
ruff format .
mypy app/ tests/
bandit -r app/ -ll -ii
```

## Docker

```bash
# Build
docker build -t gamenight .

# Run
docker run -p 8000:8000 --env-file .env gamenight
```

Or use docker-compose:

```bash
docker compose -f docker-compose.game_night.yml up
```

## CI/CD

GitHub Actions runs on every push/PR to `main`:
1. Lint (ruff)
2. Type check (mypy)
3. Security scan (bandit)
4. Docker build check
5. pytest (with PostgreSQL service)
6. Publish image to GHCR (main branch only)

## Deployment

The app is deployed at [gamenight.sgammill.com](https://gamenight.sgammill.com).

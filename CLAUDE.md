# Shortlist

Multi-agent job search copilot for senior engineers in Bangalore.
Scores offers across 8 dimensions, detects role archetypes,
tailors LaTeX resumes per JD, and tracks everything in Postgres.

Built with Anthropic Claude, Pydantic, and plain Python.

## Docker data persistence

- `docker compose up -d` — start Postgres, data preserved
- `docker compose stop` — stop container, data preserved
- `docker compose down` — remove container, data preserved
- `docker compose down -v` — DANGER: removes the data volume
  NEVER run this unless you explicitly want to wipe the database

## Database

- PostgreSQL 16 running in Docker, exposed on localhost:5432
- Connection string read from DATABASE_URL env var
- All DB access goes through tracker/tracker.py JobTracker class
- Never write raw SQL outside of tracker/db.py and tracker/tracker.py

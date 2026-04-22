# Shortlist

Multi-agent job search copilot for senior engineers in Bangalore. Scores offers across 8 dimensions, detects role archetypes, tailors LaTeX resumes per JD, and tracks everything in Postgres. Built with Claude, Pydantic, and plain Python — no frameworks.

## Prerequisites

- Python 3.11+
- Docker
- pdflatex

## Setup

1. `cp config.example.yaml config.yaml` — fill in your details
2. `cp .env.example .env` — add `ANTHROPIC_API_KEY`
3. `docker compose up -d` — starts Postgres
4. `uv sync`
5. `uv run python -c "from tracker.db import init_db; init_db()"`
6. `uv run python main.py`

## Backup & Restore

Run `scripts/backup.sh` to dump the database to `~/shortlist-backups/` (keeps the 30 most recent).

Run `scripts/restore.sh <backup-file.sql.gz>` to restore a backup — you will be asked to confirm before any data is overwritten.

> **Warning:** `docker compose down -v` permanently deletes the data volume. Use `docker compose down` (without `-v`) to stop the container while preserving data.

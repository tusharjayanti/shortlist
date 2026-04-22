import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

(Path(__file__).parent.parent / "data").mkdir(exist_ok=True)


@contextmanager
def get_connection():
    url = os.environ["DATABASE_URL"]
    # Strip SQLAlchemy driver suffixes (postgresql+psycopg2://, postgresql+asyncpg://, etc.)
    # psycopg2 only accepts the plain postgresql:// scheme
    if url.startswith("postgresql+"):
        url = "postgresql://" + url.split("://", 1)[1]
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    id TEXT PRIMARY KEY,
                    company TEXT NOT NULL,
                    role TEXT NOT NULL,
                    job_url TEXT NOT NULL,
                    tier INTEGER,
                    score INTEGER,
                    grade TEXT,
                    archetype TEXT,
                    -- status values: discovered, scored, shortlisted,
                    -- resume_tailored, cover_written, approved, applied,
                    -- interviewing, offer, rejected, withdrawn
                    status TEXT NOT NULL DEFAULT 'discovered',
                    source TEXT,
                    applied_at TIMESTAMPTZ,
                    notes TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS resume_versions (
                    id SERIAL PRIMARY KEY,
                    application_id TEXT NOT NULL REFERENCES applications(id),
                    version INTEGER NOT NULL,
                    tex_path TEXT NOT NULL,
                    pdf_path TEXT,
                    changes_summary TEXT,
                    feedback_given TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(application_id, version)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id SERIAL PRIMARY KEY,
                    application_id TEXT REFERENCES applications(id),
                    agent TEXT NOT NULL,
                    action TEXT NOT NULL,
                    input_summary TEXT,
                    output_summary TEXT,
                    tokens_used INTEGER,
                    latency_ms INTEGER,
                    success BOOLEAN NOT NULL,
                    error TEXT,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS seen_urls (
                    url TEXT PRIMARY KEY,
                    source TEXT,
                    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_application_id ON audit_logs(application_id)"
            )

import os
import uuid

from dotenv import load_dotenv

from tracker.db import get_connection, init_db

load_dotenv()


class JobTracker:
    """
    Manages job application state in Postgres.

    Valid status values: discovered, scored, shortlisted, resume_tailored,
    cover_written, approved, applied, interviewing, offer, rejected, withdrawn
    """

    def __init__(self, database_url: str | None = None):
        if database_url:
            os.environ["DATABASE_URL"] = database_url
        init_db()

    def create_application(
        self,
        company: str,
        role: str,
        job_url: str,
        tier: int | None,
        score: int | None,
        grade: str | None,
        archetype: str | None,
        source: str | None,
    ) -> str:
        app_id = uuid.uuid4().hex[:8]
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO applications
                        (id, company, role, job_url, tier, score, grade, archetype, source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (app_id, company, role, job_url, tier, score, grade, archetype, source),
                )
        return app_id

    def update_status(self, app_id: str, status: str, notes: str | None = None):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE applications SET status = %s, notes = COALESCE(%s, notes) WHERE id = %s",
                    (status, notes, app_id),
                )

    def get_application(self, app_id: str) -> dict:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM applications WHERE id = %s", (app_id,))
                return dict(cur.fetchone())

    def get_all_applications(self) -> list[dict]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM applications ORDER BY created_at DESC")
                return [dict(row) for row in cur.fetchall()]

    def get_by_status(self, status: str) -> list[dict]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM applications WHERE status = %s ORDER BY created_at DESC",
                    (status,),
                )
                return [dict(row) for row in cur.fetchall()]

    def is_seen_url(self, url: str) -> bool:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM seen_urls WHERE url = %s", (url,))
                return cur.fetchone() is not None

    def mark_url_seen(self, url: str, source: str | None = None):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO seen_urls (url, source) VALUES (%s, %s) ON CONFLICT (url) DO NOTHING",
                    (url, source),
                )

    def save_resume_version(
        self,
        app_id: str,
        tex_path: str,
        pdf_path: str | None,
        changes_summary: str | None,
        feedback_given: str | None,
    ) -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM resume_versions WHERE application_id = %s",
                    (app_id,),
                )
                current_max = cur.fetchone()["coalesce"]
                new_version = current_max + 1
                cur.execute(
                    """
                    INSERT INTO resume_versions
                        (application_id, version, tex_path, pdf_path, changes_summary, feedback_given)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (app_id, new_version, tex_path, pdf_path, changes_summary, feedback_given),
                )
        return new_version

    def get_resume_versions(self, app_id: str) -> list[dict]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM resume_versions WHERE application_id = %s ORDER BY version",
                    (app_id,),
                )
                return [dict(row) for row in cur.fetchall()]

    def log(
        self,
        app_id: str | None,
        agent: str,
        action: str,
        input_summary: str | None,
        output_summary: str | None,
        tokens_used: int | None,
        latency_ms: int | None,
        success: bool,
        error: str | None = None,
    ):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_logs
                        (application_id, agent, action, input_summary, output_summary,
                         tokens_used, latency_ms, success, error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        app_id, agent, action, input_summary, output_summary,
                        tokens_used, latency_ms, success, error,
                    ),
                )

    def get_audit_logs(self, app_id: str) -> list[dict]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM audit_logs WHERE application_id = %s ORDER BY timestamp",
                    (app_id,),
                )
                return [dict(row) for row in cur.fetchall()]

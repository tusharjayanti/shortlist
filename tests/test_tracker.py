import pytest
from testcontainers.postgres import PostgresContainer

from tracker.db import get_connection
from tracker.tracker import JobTracker


@pytest.fixture(scope="module")
def pg():
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(autouse=True)
def clean_db(pg):
    JobTracker(database_url=pg.get_connection_url())
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE seen_urls, audit_logs, resume_versions, applications RESTART IDENTITY CASCADE"
            )
    yield


@pytest.fixture
def tracker(pg):
    return JobTracker(database_url=pg.get_connection_url())


def test_create_application_returns_8_char_id(tracker):
    app_id = tracker.create_application(
        company="Acme", role="SWE", job_url="https://acme.com/job/1",
        tier=1, score=85, grade="A", archetype="backend", source="linkedin",
    )
    assert len(app_id) == 8


def test_update_status_changes_status(tracker):
    app_id = tracker.create_application(
        company="Acme", role="SWE", job_url="https://acme.com/job/2",
        tier=1, score=80, grade="B", archetype="backend", source="naukri",
    )
    tracker.update_status(app_id, "applied")
    app = tracker.get_application(app_id)
    assert app["status"] == "applied"


def test_is_seen_url_false_for_new_url(tracker):
    assert tracker.is_seen_url("https://example.com/new-job") is False


def test_mark_url_seen_then_is_seen_url_true(tracker):
    url = "https://example.com/seen-job"
    tracker.mark_url_seen(url)
    assert tracker.is_seen_url(url) is True


def test_mark_url_seen_does_not_create_application(tracker):
    url = "https://example.com/crawled-job"
    tracker.mark_url_seen(url)
    assert tracker.is_seen_url(url) is True
    assert tracker.get_all_applications() == []


def test_mark_url_seen_is_idempotent(tracker):
    url = "https://example.com/dup-job"
    tracker.mark_url_seen(url)
    tracker.mark_url_seen(url)  # should not raise
    assert tracker.is_seen_url(url) is True


def test_save_resume_version_increments(tracker):
    app_id = tracker.create_application(
        company="Acme", role="SWE", job_url="https://acme.com/job/3",
        tier=2, score=75, grade="B", archetype="fullstack", source="direct",
    )
    v1 = tracker.save_resume_version(app_id, "resume_v1.tex", "resume_v1.pdf", "initial", None)
    v2 = tracker.save_resume_version(app_id, "resume_v2.tex", "resume_v2.pdf", "tweaked", "looks good")
    assert v1 == 1
    assert v2 == 2


def test_log_writes_audit_entry(tracker):
    app_id = tracker.create_application(
        company="Foo", role="EM", job_url="https://foo.com/job/1",
        tier=1, score=90, grade="A+", archetype="em", source="referral",
    )
    tracker.log(
        app_id=app_id, agent="scorer", action="score_jd",
        input_summary="jd text", output_summary="score=90",
        tokens_used=500, latency_ms=250, success=True,
    )
    logs = tracker.get_audit_logs(app_id)
    assert len(logs) == 1
    assert logs[0]["agent"] == "scorer"
    assert logs[0]["success"] is True


def test_get_audit_logs_returns_entries_for_app_id(tracker):
    app1 = tracker.create_application(
        company="A", role="SWE", job_url="https://a.com/1",
        tier=1, score=80, grade="B", archetype="backend", source="linkedin",
    )
    app2 = tracker.create_application(
        company="B", role="SWE", job_url="https://b.com/1",
        tier=2, score=70, grade="C", archetype="frontend", source="naukri",
    )
    tracker.log(app1, "scorer", "score_jd", "in", "out", 100, 50, True)
    tracker.log(app2, "scorer", "score_jd", "in", "out", 100, 50, True)
    tracker.log(app1, "scorer", "score_jd", "in2", "out2", 200, 60, True)

    logs = tracker.get_audit_logs(app1)
    assert len(logs) == 2
    assert all(row["application_id"] == app1 for row in logs)


def test_get_by_status_filters_correctly(tracker):
    app1 = tracker.create_application(
        company="X", role="SWE", job_url="https://x.com/1",
        tier=1, score=85, grade="A", archetype="backend", source="linkedin",
    )
    app2 = tracker.create_application(
        company="Y", role="SWE", job_url="https://y.com/1",
        tier=1, score=85, grade="A", archetype="backend", source="linkedin",
    )
    tracker.update_status(app1, "shortlisted")

    shortlisted = tracker.get_by_status("shortlisted")
    discovered = tracker.get_by_status("discovered")

    assert any(r["id"] == app1 for r in shortlisted)
    assert not any(r["id"] == app1 for r in discovered)
    assert any(r["id"] == app2 for r in discovered)


def test_create_application_persists_all_fields(tracker):
    app_id = tracker.create_application(
        company="DeepMind", role="Staff SWE", job_url="https://deepmind.com/job/99",
        tier=1, score=95, grade="A+", archetype="ml_infra", source="referral",
    )
    app = tracker.get_application(app_id)
    assert app["company"] == "DeepMind"
    assert app["role"] == "Staff SWE"
    assert app["job_url"] == "https://deepmind.com/job/99"
    assert app["tier"] == 1
    assert app["score"] == 95
    assert app["grade"] == "A+"
    assert app["archetype"] == "ml_infra"
    assert app["source"] == "referral"
    assert app["status"] == "discovered"

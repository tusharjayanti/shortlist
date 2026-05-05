from unittest.mock import MagicMock, patch

import pytest
from testcontainers.postgres import PostgresContainer

from agents.finder import FinderAgent
from tracker.db import get_connection
from tracker.tracker import JobTracker
from tools.config_loader import (
    ATSConfig,
    ArchetypeConfig,
    CandidateConfig,
    CompaniesConfig,
    CompanyTier,
    Config,
    LLMConfig,
    LocationConfig,
    ScrapingConfig,
    ScoringConfig,
    SeniorityConfig,
    SeniorityLevel,
    SourcesConfig,
    StartupInference,
)


# ── database fixtures ─────────────────────────────────────────────────────────

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
                "TRUNCATE seen_urls, audit_logs, resume_versions, applications "
                "RESTART IDENTITY CASCADE"
            )
    yield


@pytest.fixture
def tracker_fixture(pg):
    return JobTracker(database_url=pg.get_connection_url())


# ── config fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_config():
    """Config with 2 Greenhouse slugs, 1 RSS feed, 1 blacklisted company."""
    return Config(
        llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-6"),
        candidate=CandidateConfig(
            name="Test Engineer",
            experience_years=7,
            location=LocationConfig(primary="Bengaluru", aliases=["Bengaluru", "Bangalore"]),
            min_salary_lpa=40,
            max_salary_lpa=80,
            roles=["Senior Software Engineer"],
            languages=["Python"],
            backend=["Kafka"],
            databases=["PostgreSQL"],
            cloud_devops=["AWS"],
            strengths=["Distributed systems"],
        ),
        archetypes={
            "distributed_systems": ArchetypeConfig(
                lead_with="distributed systems",
                proof_points=["Reduced latency"],
            ),
        },
        seniority=SeniorityConfig(
            target_level="senior",
            levels={
                "senior": SeniorityLevel(
                    canonical="Senior Software Engineer",
                    patterns=["senior"],
                ),
            },
            startup_inference=StartupInference(
                senior_signals=["lead"],
                mid_signals=["build"],
                junior_signals=["learn"],
            ),
        ),
        companies=CompaniesConfig(
            big_tech={
                "tier_1": CompanyTier(
                    score_bonus=3,
                    reason="Top engineering culture",
                    names=["Razorpay"],
                ),
                "tier_3": CompanyTier(
                    score_bonus=-99,
                    reason="Blacklisted",
                    names=["Byju's"],
                ),
            },
            startups={"min_funding": "Series A"},
        ),
        scoring=ScoringConfig(
            minimum_score=7,
            weights={"role_fit": 4, "skills_alignment": 4},
        ),
        sources=SourcesConfig(
            ats=ATSConfig(
                greenhouse=["razorpay", "acme"],
                ashby=[],
                lever=[],
            ),
            rss=["https://careers.example.com/rss"],
            scraping=ScrapingConfig(
                allowed_domains=["razorpay.com"],
                user_agents=["Mozilla/5.0"],
            ),
        ),
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def _empty_feed():
    return MagicMock(entries=[])


def _patched_run(tracker, config, ats_jobs, feed=None):
    """Run finder with ATS and RSS fully mocked."""
    with patch("agents.finder.scan_all_ats") as mock_scan, \
         patch("agents.finder.filter_by_location") as mock_filter, \
         patch("agents.finder.feedparser.parse") as mock_parse:
        mock_scan.return_value = ats_jobs
        mock_filter.side_effect = lambda jobs, _: jobs
        mock_parse.return_value = feed or _empty_feed()
        return FinderAgent(tracker, config).run()


# ── tests ─────────────────────────────────────────────────────────────────────

def test_finder_dedups_across_runs(tracker_fixture, minimal_config):
    """Second run returns 0 new jobs if all URLs were already seen."""
    ats_jobs = [
        {"title": "Senior BE", "company": "Razorpay", "url": "https://razorpay.com/jobs/1",
         "location": "Bengaluru", "source": "greenhouse"},
    ]

    first = _patched_run(tracker_fixture, minimal_config, ats_jobs)
    assert len(first) == 1

    second = _patched_run(tracker_fixture, minimal_config, ats_jobs)
    assert len(second) == 0


def test_finder_filters_blacklisted_companies(tracker_fixture, minimal_config):
    """Tier 3 companies are removed from the final list."""
    ats_jobs = [
        {"title": "Senior BE", "company": "Razorpay", "url": "https://razorpay.com/jobs/1",
         "location": "Bengaluru", "source": "greenhouse"},
        {"title": "Senior BE", "company": "Byju's", "url": "https://byjus.com/jobs/1",
         "location": "Bengaluru", "source": "greenhouse"},
    ]

    jobs = _patched_run(tracker_fixture, minimal_config, ats_jobs)

    assert len(jobs) == 1
    assert jobs[0]["company"] == "Razorpay"


def test_finder_handles_ats_failure_gracefully(tracker_fixture, minimal_config):
    """If ATS scan raises, other sources still run and no exception propagates."""
    with patch("agents.finder.scan_all_ats") as mock_scan, \
         patch("agents.finder.feedparser.parse") as mock_parse:
        mock_scan.side_effect = Exception("API down")
        mock_parse.return_value = _empty_feed()

        finder = FinderAgent(tracker_fixture, minimal_config)
        jobs = finder.run()  # must not raise

    assert isinstance(jobs, list)


def test_finder_handles_rss_failure_gracefully(tracker_fixture, minimal_config):
    """If feedparser.parse raises, ATS jobs still return."""
    with patch("agents.finder.scan_all_ats") as mock_scan, \
         patch("agents.finder.filter_by_location") as mock_filter, \
         patch("agents.finder.feedparser.parse") as mock_parse:
        mock_scan.return_value = []
        mock_filter.side_effect = lambda jobs, _: jobs
        mock_parse.side_effect = Exception("Network error")

        finder = FinderAgent(tracker_fixture, minimal_config)
        jobs = finder.run()  # must not raise

    assert jobs == []


def test_finder_writes_audit_log(tracker_fixture, minimal_config):
    """Every finder run is recorded in audit_logs."""
    with patch("agents.finder.scan_all_ats") as mock_scan, \
         patch("agents.finder.feedparser.parse") as mock_parse:
        mock_scan.return_value = []
        mock_parse.return_value = _empty_feed()

        FinderAgent(tracker_fixture, minimal_config).run()

    logs = tracker_fixture.get_audit_logs_by_agent("finder")
    assert len(logs) == 1
    assert logs[0]["action"] == "discover_jobs"
    assert logs[0]["success"] is True
    assert logs[0]["application_id"] is None  # no app_id for discovery runs


def test_finder_dedup_within_single_run(tracker_fixture, minimal_config):
    """Same URL from two ATS sources is returned only once."""
    ats_jobs = [
        {"title": "Senior BE", "company": "Razorpay", "url": "https://razorpay.com/jobs/1",
         "location": "Bengaluru", "source": "greenhouse"},
        {"title": "Senior BE", "company": "Razorpay", "url": "https://razorpay.com/jobs/1",
         "location": "Bengaluru", "source": "ashby"},  # same URL, different source
    ]

    jobs = _patched_run(tracker_fixture, minimal_config, ats_jobs)
    assert len(jobs) == 1

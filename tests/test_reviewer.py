import json
from unittest.mock import MagicMock, patch

import pytest

from agents.reviewer import ReviewerAgent
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
from tools.schemas import ReviewResult


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_config():
    """Minimal valid Config — same pattern as test_scorer.py."""
    return Config(
        llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-6"),
        candidate=CandidateConfig(
            name="Test Engineer",
            experience_years=7,
            location=LocationConfig(primary="Bengaluru", aliases=["Bengaluru", "Bangalore"]),
            min_salary_lpa=40,
            max_salary_lpa=80,
            roles=["Senior Software Engineer"],
            languages=["Python", "Go"],
            backend=["gRPC", "Kafka"],
            databases=["PostgreSQL"],
            cloud_devops=["AWS"],
            strengths=["Distributed systems"],
        ),
        archetypes={
            "fintech_platform": ArchetypeConfig(
                lead_with="payments correctness at scale",
                proof_points=["Reserve Release flow"],
            ),
            "distributed_systems": ArchetypeConfig(
                lead_with="distributed systems",
                proof_points=["Reduced p99 latency"],
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
            },
            startups={"min_funding": "Series A"},
        ),
        scoring=ScoringConfig(
            minimum_score=7,
            weights={"role_fit": 4, "skills_alignment": 4},
        ),
        sources=SourcesConfig(
            ats=ATSConfig(),
            scraping=ScrapingConfig(
                allowed_domains=["razorpay.com"],
                user_agents=["Mozilla/5.0"],
            ),
        ),
    )


@pytest.fixture
def mock_tracker():
    return MagicMock()


@pytest.fixture
def mock_llm_response():
    def _make(text):
        r = MagicMock()
        r.text = text
        r.input_tokens = 100
        r.output_tokens = 50
        return r
    return _make


@pytest.fixture
def valid_review_json():
    return json.dumps({
        "verdict": "Strong Fit",
        "overall_confidence": 0.92,
        "strengths": [
            "7 years backend matches seniority ask",
            "Kafka + PostgreSQL exact stack match",
        ],
        "gaps": ["No payments domain experience mentioned"],
        "missing_keywords": ["idempotency", "PCI", "webhooks"],
        "strategic_angle": "Lead with Reserve Release correctness at scale.",
        "prioritized_edits": [
            {
                "priority": "high",
                "change": "Rewrite summary to lead with fintech framing",
                "rationale": "ATS prioritises candidates who mirror JD language",
            },
            {
                "priority": "medium",
                "change": "Add idempotency mention to DISCO bullet",
                "rationale": "Missing keyword that JD explicitly requires",
            },
        ],
    })


@pytest.fixture
def fintech_job():
    return {
        "company": "Razorpay",
        "title": "Senior Backend Engineer",
        "description": "Build payments infrastructure with idempotency and webhooks.",
        "location": "Bengaluru",
        "url": "https://razorpay.com/jobs/1",
    }


SAMPLE_RESUME = (
    "Test Engineer\n"
    "Senior Software Engineer with 7 years of backend experience.\n"
    "Built distributed systems with Kafka and PostgreSQL at scale."
)


# ── tests ─────────────────────────────────────────────────────────────────────

def test_reviewer_returns_valid_review_result(
    minimal_config, mock_tracker, mock_llm_response, valid_review_json, fintech_job
):
    with patch("agents.reviewer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_review_json)
        mock_get_llm.return_value = mock_llm

        reviewer = ReviewerAgent(mock_tracker, minimal_config)
        result = reviewer.run("app-123", fintech_job, "fintech_platform", SAMPLE_RESUME)

    assert isinstance(result, ReviewResult)
    assert result.verdict == "Strong Fit"
    assert result.overall_confidence == 0.92
    assert "idempotency" in result.missing_keywords
    assert result.prioritized_edits[0].priority == "high"


def test_reviewer_retries_on_invalid_json(
    minimal_config, mock_tracker, mock_llm_response, valid_review_json, fintech_job
):
    with patch("agents.reviewer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = [
            mock_llm_response("not valid json"),
            mock_llm_response("still not json"),
            mock_llm_response(valid_review_json),
        ]
        mock_get_llm.return_value = mock_llm

        reviewer = ReviewerAgent(mock_tracker, minimal_config)
        result = reviewer.run("app-123", fintech_job, "fintech_platform", SAMPLE_RESUME)

    assert mock_llm.complete.call_count == 3
    assert isinstance(result, ReviewResult)


def test_reviewer_raises_after_max_retries(
    minimal_config, mock_tracker, mock_llm_response, fintech_job
):
    with patch("agents.reviewer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response("not json at all")
        mock_get_llm.return_value = mock_llm

        reviewer = ReviewerAgent(mock_tracker, minimal_config)

        with pytest.raises(RuntimeError, match="failed after 3 retries"):
            reviewer.run("app-123", fintech_job, "fintech_platform", SAMPLE_RESUME)

    assert mock_llm.complete.call_count == 3


def test_reviewer_includes_archetype_in_user_message(
    minimal_config, mock_tracker, mock_llm_response, valid_review_json, fintech_job
):
    with patch("agents.reviewer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_review_json)
        mock_get_llm.return_value = mock_llm

        reviewer = ReviewerAgent(mock_tracker, minimal_config)
        reviewer.run("app-123", fintech_job, "fintech_platform", SAMPLE_RESUME)

    user_message = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
    assert "fintech_platform" in user_message


def test_reviewer_includes_resume_in_user_message(
    minimal_config, mock_tracker, mock_llm_response, valid_review_json, fintech_job
):
    with patch("agents.reviewer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_review_json)
        mock_get_llm.return_value = mock_llm

        reviewer = ReviewerAgent(mock_tracker, minimal_config)
        reviewer.run("app-123", fintech_job, "fintech_platform", SAMPLE_RESUME)

    user_message = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
    assert SAMPLE_RESUME in user_message


def test_reviewer_populates_tokens_used(
    minimal_config, mock_tracker, mock_llm_response, valid_review_json, fintech_job
):
    with patch("agents.reviewer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_review_json)
        mock_get_llm.return_value = mock_llm

        reviewer = ReviewerAgent(mock_tracker, minimal_config)
        reviewer.run("app-123", fintech_job, "fintech_platform", SAMPLE_RESUME)

    assert reviewer._last_llm_response is not None
    assert reviewer._last_llm_response.input_tokens == 100
    assert reviewer._last_llm_response.output_tokens == 50

    log_kwargs = mock_tracker.log.call_args.kwargs
    assert log_kwargs["tokens_used"] == 150


def test_reviewer_handles_empty_resume(
    minimal_config, mock_tracker, mock_llm_response, valid_review_json, fintech_job
):
    with patch("agents.reviewer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_review_json)
        mock_get_llm.return_value = mock_llm

        reviewer = ReviewerAgent(mock_tracker, minimal_config)
        result = reviewer.run("app-123", fintech_job, "fintech_platform", "")

    assert isinstance(result, ReviewResult)
    assert mock_llm.complete.call_count == 1


def test_reviewer_verdict_must_be_valid_literal(
    minimal_config, mock_tracker, mock_llm_response, valid_review_json, fintech_job
):
    invalid_verdict_json = json.dumps({
        "verdict": "Amazing Fit",
        "overall_confidence": 0.9,
        "strengths": ["x"],
        "gaps": ["y"],
        "missing_keywords": ["z"],
        "strategic_angle": "Lead with backend depth.",
        "prioritized_edits": [
            {"priority": "high", "change": "do X", "rationale": "because Y"},
        ],
    })

    with patch("agents.reviewer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = [
            mock_llm_response(invalid_verdict_json),
            mock_llm_response(valid_review_json),
        ]
        mock_get_llm.return_value = mock_llm

        reviewer = ReviewerAgent(mock_tracker, minimal_config)
        result = reviewer.run("app-123", fintech_job, "fintech_platform", SAMPLE_RESUME)

    assert mock_llm.complete.call_count == 2
    assert result.verdict == "Strong Fit"

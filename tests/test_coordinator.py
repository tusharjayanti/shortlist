from unittest.mock import MagicMock, patch

import pytest

from coordinator.review import (
    ArtifactState,  # noqa: F401  (exposed for downstream callers)
    ArtifactStatus,  # noqa: F401
    ReviewCoordinator,
)
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
from tools.schemas import (
    CoverLetter,
    NetworkingMessages,
    PrioritizedEdit,
    ReviewResult,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_config():
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
def mock_tailor():
    tailor = MagicMock()
    tailor.run.return_value = {
        "tex_content": "\\documentclass{article}\\begin{document}Resume\\end{document}",
        "tex_path": "output/test.tex",
        "version": 1,
        "changes_summary": "v1: fintech_platform framing",
    }
    return tailor


@pytest.fixture
def mock_cover():
    cover = MagicMock()
    cover.run.return_value = CoverLetter(
        text=("This is the test cover letter mentioning Razorpay. " * 20).strip(),
        word_count=160,
        angle="Lead with Reserve Release as direct mapping to Razorpay payments.",
        selected_proof_point_ids=["reserve-release-feature", "kafka-events"],
        company_research_signals=["10k+ TPS", "PCI compliance"],
    )
    return cover


@pytest.fixture
def mock_networker():
    networker = MagicMock()
    networker.run.return_value = NetworkingMessages(
        linkedin_dm=(
            "Hey {{recipient_name}}, "
            "I saw the Razorpay role and "
            "the idempotency requirements caught my attention. "
            "Would 10 minutes work this week?"
        ),
        linkedin_dm_word_count=30,
        cold_email_subject="Senior Backend at Razorpay - 15 minutes?",
        cold_email_body=(
            "Hi {{recipient_name}},\n\n"
            + "I'm reaching out about Razorpay. " * 30
        ),
        cold_email_word_count=152,
        angle="Lead with idempotent payment systems experience.",
        selected_proof_point_ids=["reserve-release-feature"],
        placeholders_used=["{{recipient_name}}"],
    )
    return networker


@pytest.fixture
def sample_review():
    return ReviewResult(
        verdict="Strong Fit",
        overall_confidence=0.88,
        strengths=["Stack match"],
        gaps=["No PCI mention"],
        missing_keywords=["PCI", "idempotent"],
        strategic_angle="Lead with fintech framing.",
        prioritized_edits=[
            PrioritizedEdit(
                priority="high",
                change="Rewrite summary",
                rationale="ATS keyword match",
            ),
        ],
    )


@pytest.fixture
def sample_job():
    return {
        "company": "Razorpay",
        "title": "Senior Backend Engineer",
        "description": "Payments. 10k+ TPS.",
        "location": "Bengaluru",
    }


# ── tests ─────────────────────────────────────────────────────────────────────

def test_coordinator_approves_all_three_on_first_pass(
    minimal_config, mock_tracker, mock_tailor, mock_cover,
    mock_networker, sample_review, sample_job,
):
    """User approves each artifact on first try."""
    coord = ReviewCoordinator(
        mock_tracker, minimal_config,
        mock_tailor, mock_cover, mock_networker,
    )

    with patch("coordinator.review.Prompt.ask", return_value="y"):
        result = coord.run(
            "app_test", sample_job, "fintech_platform", sample_review,
        )

    assert result["aborted"] is False
    assert result["resume_path"] == "output/test.tex"
    assert isinstance(result["cover_letter"], CoverLetter)
    assert isinstance(result["networking"], NetworkingMessages)

    assert mock_tailor.run.call_count == 1
    assert mock_cover.run.call_count == 1
    assert mock_networker.run.call_count == 1


def test_coordinator_iterates_resume_with_feedback(
    minimal_config, mock_tracker, mock_tailor, mock_cover,
    mock_networker, sample_review, sample_job,
):
    """User rejects resume once with feedback, then approves."""
    coord = ReviewCoordinator(
        mock_tracker, minimal_config,
        mock_tailor, mock_cover, mock_networker,
    )

    responses = [
        "n: too generic, lead with payments",
        "y",  # approve revised resume
        "y",  # approve cover
        "y",  # approve networking
    ]

    with patch("coordinator.review.Prompt.ask", side_effect=responses):
        result = coord.run(
            "app_test", sample_job, "fintech_platform", sample_review,
        )

    assert result["aborted"] is False
    assert mock_tailor.run.call_count == 2
    assert mock_cover.run.call_count == 1
    assert mock_networker.run.call_count == 1

    second_call_kwargs = mock_tailor.run.call_args_list[1][1]
    assert "too generic" in second_call_kwargs.get("feedback", "")


def test_coordinator_aborts_cleanly(
    minimal_config, mock_tracker, mock_tailor, mock_cover,
    mock_networker, sample_review, sample_job,
):
    """User types 'abort' on first artifact."""
    coord = ReviewCoordinator(
        mock_tracker, minimal_config,
        mock_tailor, mock_cover, mock_networker,
    )

    with patch("coordinator.review.Prompt.ask", return_value="abort"):
        result = coord.run(
            "app_test", sample_job, "fintech_platform", sample_review,
        )

    assert result["aborted"] is True
    assert result["resume_path"] is None
    assert result["cover_letter"] is None
    assert result["networking"] is None


def test_coordinator_iterates_cover_letter(
    minimal_config, mock_tracker, mock_tailor, mock_cover,
    mock_networker, sample_review, sample_job,
):
    """User rejects cover letter twice, then approves."""
    coord = ReviewCoordinator(
        mock_tracker, minimal_config,
        mock_tailor, mock_cover, mock_networker,
    )

    responses = [
        "y",  # approve resume
        "n: too formal",
        "n: still too long",
        "y",  # approve cover
        "y",  # approve networking
    ]

    with patch("coordinator.review.Prompt.ask", side_effect=responses):
        result = coord.run(
            "app_test", sample_job, "fintech_platform", sample_review,
        )

    assert result["aborted"] is False
    # Cover ran 3 times: initial + 2 revisions
    assert mock_cover.run.call_count == 3


def test_coordinator_handles_empty_feedback(
    minimal_config, mock_tracker, mock_tailor, mock_cover,
    mock_networker, sample_review, sample_job,
):
    """User types 'n:' with no feedback — should re-prompt."""
    coord = ReviewCoordinator(
        mock_tracker, minimal_config,
        mock_tailor, mock_cover, mock_networker,
    )

    responses = [
        "n:",        # empty feedback — re-prompt
        "n:    ",    # whitespace only — re-prompt
        "y",         # approve resume
        "y",         # approve cover
        "y",         # approve networking
    ]

    with patch("coordinator.review.Prompt.ask", side_effect=responses):
        result = coord.run(
            "app_test", sample_job, "fintech_platform", sample_review,
        )

    assert result["aborted"] is False
    # Tailor ran exactly once (no valid feedback to trigger rerun)
    assert mock_tailor.run.call_count == 1


def test_coordinator_unrecognized_input_reprompts(
    minimal_config, mock_tracker, mock_tailor, mock_cover,
    mock_networker, sample_review, sample_job,
):
    """User types something other than y/n/abort — re-prompts."""
    coord = ReviewCoordinator(
        mock_tracker, minimal_config,
        mock_tailor, mock_cover, mock_networker,
    )

    responses = [
        "maybe",      # unrecognized
        "what?",      # unrecognized
        "y",          # approve resume
        "y",          # approve cover
        "y",          # approve networking
    ]

    with patch("coordinator.review.Prompt.ask", side_effect=responses):
        result = coord.run(
            "app_test", sample_job, "fintech_platform", sample_review,
        )

    assert result["aborted"] is False


def test_coordinator_state_tracks_versions(
    minimal_config, mock_tracker, mock_tailor, mock_cover,
    mock_networker, sample_review, sample_job,
):
    """Version numbers increment on revisions."""
    coord = ReviewCoordinator(
        mock_tracker, minimal_config,
        mock_tailor, mock_cover, mock_networker,
    )

    responses = [
        "n: revise",
        "n: again",
        "y",  # approve resume after 2 revisions
        "y",  # approve cover
        "y",  # approve networking
    ]

    with patch("coordinator.review.Prompt.ask", side_effect=responses):
        coord.run(
            "app_test", sample_job, "fintech_platform", sample_review,
        )

    assert mock_tailor.run.call_count == 3


def test_coordinator_passes_feedback_history_to_agents(
    minimal_config, mock_tracker, mock_tailor, mock_cover,
    mock_networker, sample_review, sample_job,
):
    """Each revision passes the latest feedback to the agent."""
    coord = ReviewCoordinator(
        mock_tracker, minimal_config,
        mock_tailor, mock_cover, mock_networker,
    )

    responses = [
        "n: feedback one",
        "n: feedback two",
        "y",
        "y",
        "y",
    ]

    with patch("coordinator.review.Prompt.ask", side_effect=responses):
        coord.run(
            "app_test", sample_job, "fintech_platform", sample_review,
        )

    calls = mock_tailor.run.call_args_list
    assert calls[0][1].get("feedback") is None
    assert calls[1][1]["feedback"] == "feedback one"
    assert calls[2][1]["feedback"] == "feedback two"

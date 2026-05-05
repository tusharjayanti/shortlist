from unittest.mock import MagicMock, patch

import pytest

from agents.tailor import TailorAgent
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
from tools.schemas import PrioritizedEdit, ReviewResult


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_config():
    """Config with at least one archetype configured."""
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
    tracker = MagicMock()
    tracker.save_resume_version.return_value = 1
    return tracker


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
def sample_resume_tex():
    return r"""\documentclass[a4paper]{article}
\begin{document}
\section*{Tushar Jayanti}
Senior Backend Engineer with 7 years experience.

\section*{Experience}
\textbf{DISCO} — Senior Software Engineer \\
Led migration of identity platform. Reduced p99 latency
from 4.2s to 1s.

\textbf{Transcend Street Solutions} — Software Engineer \\
Engineered Reserve Release feature preventing incorrect
financial orders across 10k+ daily transactions.

\section*{Education}
MS Computer Science, NJIT
\end{document}
"""


@pytest.fixture
def sample_review():
    return ReviewResult(
        verdict="Strong Fit",
        overall_confidence=0.88,
        strengths=["Stack match", "Scale experience"],
        gaps=["No PCI mention"],
        missing_keywords=["PCI", "idempotent"],
        strategic_angle="Lead with fintech framing.",
        prioritized_edits=[
            PrioritizedEdit(
                priority="high",
                change="Rewrite summary for fintech",
                rationale="ATS keyword match",
            )
        ],
    )


@pytest.fixture
def sample_job():
    return {
        "company": "Razorpay",
        "title": "Senior Backend Engineer",
        "description": "Payments platform. 10k+ TPS.",
        "location": "Bengaluru",
    }


# ── tests ─────────────────────────────────────────────────────────────────────

def test_tailor_returns_valid_latex(
    minimal_config, mock_tracker, mock_llm_response,
    sample_resume_tex, sample_review, sample_job,
):
    with patch("agents.tailor.get_active_llm") as mock_get_llm, \
         patch("agents.tailor.write_tailored_resume") as mock_write:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(sample_resume_tex)
        mock_get_llm.return_value = mock_llm
        mock_write.return_value = "/tmp/fake/razorpay-senior-backend-engineer.tex"

        tailor = TailorAgent(mock_tracker, minimal_config)
        result = tailor.run(
            "app-123", sample_job, "fintech_platform",
            sample_review, resume_tex=sample_resume_tex,
        )

    assert set(result.keys()) == {"tex_content", "tex_path", "version", "changes_summary"}
    assert result["tex_content"].startswith("\\documentclass")
    assert result["version"] == 1


def test_tailor_rejects_non_latex_output(
    minimal_config, mock_tracker, mock_llm_response,
    sample_resume_tex, sample_review, sample_job,
):
    with patch("agents.tailor.get_active_llm") as mock_get_llm, \
         patch("agents.tailor.write_tailored_resume"):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(
            "Here is your tailored resume: I'd be happy to help."
        )
        mock_get_llm.return_value = mock_llm

        tailor = TailorAgent(mock_tracker, minimal_config)
        with pytest.raises(RuntimeError, match=r"\\documentclass"):
            tailor.run(
                "app-123", sample_job, "fintech_platform",
                sample_review, resume_tex=sample_resume_tex,
            )


def test_tailor_strips_markdown_fences(
    minimal_config, mock_tracker, mock_llm_response,
    sample_resume_tex, sample_review, sample_job,
):
    fenced = "```latex\n" + sample_resume_tex + "\n```"
    with patch("agents.tailor.get_active_llm") as mock_get_llm, \
         patch("agents.tailor.write_tailored_resume") as mock_write:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(fenced)
        mock_get_llm.return_value = mock_llm
        mock_write.return_value = "/tmp/fake.tex"

        tailor = TailorAgent(mock_tracker, minimal_config)
        result = tailor.run(
            "app-123", sample_job, "fintech_platform",
            sample_review, resume_tex=sample_resume_tex,
        )

    assert result["tex_content"].startswith("\\documentclass")
    assert "```" not in result["tex_content"]


def test_tailor_saves_version_to_tracker(
    minimal_config, mock_tracker, mock_llm_response,
    sample_resume_tex, sample_review, sample_job,
):
    with patch("agents.tailor.get_active_llm") as mock_get_llm, \
         patch("agents.tailor.write_tailored_resume") as mock_write:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(sample_resume_tex)
        mock_get_llm.return_value = mock_llm
        mock_write.return_value = "/tmp/fake.tex"

        tailor = TailorAgent(mock_tracker, minimal_config)
        result = tailor.run(
            "app-123", sample_job, "fintech_platform",
            sample_review, resume_tex=sample_resume_tex,
        )

    mock_tracker.save_resume_version.assert_called_once()
    save_kwargs = mock_tracker.save_resume_version.call_args.kwargs
    assert save_kwargs["app_id"] == "app-123"
    assert save_kwargs["tex_path"] == "/tmp/fake.tex"
    assert save_kwargs["pdf_path"] is None
    assert result["version"] == 1


def test_tailor_includes_feedback_in_prompt(
    minimal_config, mock_tracker, mock_llm_response,
    sample_resume_tex, sample_review, sample_job,
):
    with patch("agents.tailor.get_active_llm") as mock_get_llm, \
         patch("agents.tailor.write_tailored_resume") as mock_write:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(sample_resume_tex)
        mock_get_llm.return_value = mock_llm
        mock_write.return_value = "/tmp/fake.tex"

        tailor = TailorAgent(mock_tracker, minimal_config)
        tailor.run(
            "app-123", sample_job, "fintech_platform",
            sample_review, resume_tex=sample_resume_tex,
            feedback="tone down the summary",
        )

    user_message = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
    assert "tone down the summary" in user_message


def test_tailor_includes_archetype_in_system_prompt(
    minimal_config, mock_tracker, mock_llm_response,
    sample_resume_tex, sample_review, sample_job,
):
    with patch("agents.tailor.get_active_llm") as mock_get_llm, \
         patch("agents.tailor.write_tailored_resume") as mock_write:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(sample_resume_tex)
        mock_get_llm.return_value = mock_llm
        mock_write.return_value = "/tmp/fake.tex"

        tailor = TailorAgent(mock_tracker, minimal_config)
        tailor.run(
            "app-123", sample_job, "fintech_platform",
            sample_review, resume_tex=sample_resume_tex,
        )

    system_prompt = mock_llm.complete.call_args.kwargs["system_prompt"]
    assert "fintech_platform" in system_prompt
    assert "payments correctness at scale" in system_prompt


def test_tailor_uses_low_temperature(
    minimal_config, mock_tracker, mock_llm_response,
    sample_resume_tex, sample_review, sample_job,
):
    with patch("agents.tailor.get_active_llm") as mock_get_llm, \
         patch("agents.tailor.write_tailored_resume") as mock_write:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(sample_resume_tex)
        mock_get_llm.return_value = mock_llm
        mock_write.return_value = "/tmp/fake.tex"

        tailor = TailorAgent(mock_tracker, minimal_config)
        tailor.run(
            "app-123", sample_job, "fintech_platform",
            sample_review, resume_tex=sample_resume_tex,
        )

    call_kwargs = mock_llm.complete.call_args.kwargs
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["max_tokens"] == 8192


def test_tailor_enforces_length_guardrail(
    minimal_config, mock_tracker, mock_llm_response,
    sample_resume_tex, sample_review, sample_job,
):
    short_latex = "\\documentclass{article}\\begin{document}x\\end{document}"
    with patch("agents.tailor.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(short_latex)
        mock_get_llm.return_value = mock_llm

        tailor = TailorAgent(mock_tracker, minimal_config)
        with pytest.raises(ValueError, match="less than 70%"):
            tailor.run(
                "app-123", sample_job, "fintech_platform",
                sample_review, resume_tex=sample_resume_tex,
            )



import logging
from pathlib import Path
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
from tools.schemas import (
    Corpus,
    CorpusBullet,
    CorpusRole,
    PrioritizedEdit,
    ReviewResult,
)

CORPUS_FIXTURE_PATH = str(
    Path(__file__).parent / "fixtures" / "test_experience.md"
)


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


@pytest.fixture
def sample_corpus():
    """Build a Corpus object for testing."""
    return Corpus(
        name="Test User",
        roles=[
            CorpusRole(
                role_id="acme-corp-senior-engineer",
                company="Acme Corp",
                title="Senior Engineer",
                dates="2023 - Present",
                tech_stack=["Python", "PostgreSQL"],
                bullets=[
                    CorpusBullet(
                        role_id="acme-corp-senior-engineer",
                        bullet_id="built-data-pipeline",
                        title="Built data pipeline",
                        text="Built a scalable data pipeline processing 1M+ records daily.",
                    ),
                    CorpusBullet(
                        role_id="acme-corp-senior-engineer",
                        bullet_id="migrated-to-microservices",
                        title="Migrated to microservices",
                        text="Led migration of monolithic billing service into 4 microservices.",
                    ),
                ],
            ),
        ],
    )


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
            corpus_path=CORPUS_FIXTURE_PATH,
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
                corpus_path=CORPUS_FIXTURE_PATH,
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
            corpus_path=CORPUS_FIXTURE_PATH,
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
            corpus_path=CORPUS_FIXTURE_PATH,
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
            corpus_path=CORPUS_FIXTURE_PATH,
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
            corpus_path=CORPUS_FIXTURE_PATH,
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
            corpus_path=CORPUS_FIXTURE_PATH,
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
                corpus_path=CORPUS_FIXTURE_PATH,
            )


# ── corpus integration tests ──────────────────────────────────────────────────

def test_tailor_passes_both_sources_to_prompt(
    minimal_config, mock_tracker, mock_llm_response,
    sample_resume_tex, sample_review, sample_job, sample_corpus,
):
    with patch("agents.tailor.get_active_llm") as mock_get_llm, \
         patch("agents.tailor.write_tailored_resume") as mock_write, \
         patch("agents.tailor.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(sample_resume_tex)
        mock_get_llm.return_value = mock_llm
        mock_write.return_value = "/tmp/fake.tex"

        tailor = TailorAgent(mock_tracker, minimal_config)
        tailor.run(
            "app-123", sample_job, "fintech_platform",
            sample_review, resume_tex=sample_resume_tex,
        )

    user_message = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
    # resume content present
    assert "Tushar Jayanti" in user_message
    assert "DISCO" in user_message
    # corpus content present
    assert "Acme Corp" in user_message
    assert "Built data pipeline" in user_message


def test_tailor_format_corpus_for_prompt_includes_all_roles(
    minimal_config, mock_tracker, sample_corpus,
):
    with patch("agents.tailor.get_active_llm"):
        tailor = TailorAgent(mock_tracker, minimal_config)

    formatted = tailor._format_corpus_for_prompt(sample_corpus)

    assert "Acme Corp" in formatted
    assert "Built data pipeline" in formatted
    assert "Migrated to microservices" in formatted
    assert "Python, PostgreSQL" in formatted
    assert "2023 - Present" in formatted


def test_tailor_warns_on_suspicious_tokens(
    minimal_config, mock_tracker, mock_llm_response,
    sample_resume_tex, sample_review, sample_job, sample_corpus, caplog,
):
    # LaTeX containing a token (\textbf{Spotify}) that's in neither
    # resume.tex nor the corpus
    fabricated = sample_resume_tex.replace(
        r"\textbf{DISCO}", r"\textbf{Spotify}"
    )

    with patch("agents.tailor.get_active_llm") as mock_get_llm, \
         patch("agents.tailor.write_tailored_resume") as mock_write, \
         patch("agents.tailor.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(fabricated)
        mock_get_llm.return_value = mock_llm
        mock_write.return_value = "/tmp/fake.tex"

        tailor = TailorAgent(mock_tracker, minimal_config)
        with caplog.at_level(logging.WARNING):
            tailor.run(
                "app-123", sample_job, "fintech_platform",
                sample_review, resume_tex=sample_resume_tex,
            )

    assert "Spotify" in caplog.text
    assert "fabrication" in caplog.text.lower()


def test_tailor_no_warning_when_all_content_traces(
    minimal_config, mock_tracker, mock_llm_response,
    sample_resume_tex, sample_review, sample_job, sample_corpus, caplog,
):
    # Every \textbf{...} in sample_resume_tex traces to itself
    with patch("agents.tailor.get_active_llm") as mock_get_llm, \
         patch("agents.tailor.write_tailored_resume") as mock_write, \
         patch("agents.tailor.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(sample_resume_tex)
        mock_get_llm.return_value = mock_llm
        mock_write.return_value = "/tmp/fake.tex"

        tailor = TailorAgent(mock_tracker, minimal_config)
        with caplog.at_level(logging.WARNING, logger="root"):
            tailor.run(
                "app-123", sample_job, "fintech_platform",
                sample_review, resume_tex=sample_resume_tex,
            )

    fabrication_warnings = [
        r for r in caplog.records
        if "fabrication" in r.getMessage().lower()
    ]
    assert fabrication_warnings == []

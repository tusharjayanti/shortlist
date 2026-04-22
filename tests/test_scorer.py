import json
from unittest.mock import MagicMock, patch

import pytest

from agents.scorer import ScorerAgent, _strip_fences
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
from tools.schemas import JobScore


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_config():
    """Minimal valid Config with one tier-1 and one tier-3 company."""
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
                "tier_3": CompanyTier(
                    score_bonus=-99,
                    reason="Blacklisted — never surfaced",
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


def _strong_match_json():
    return json.dumps({
        "role_fit": 4, "skills_alignment": 4, "seniority_fit": 2,
        "salary_signal": 2, "interview_likelihood": 2,
        "growth_trajectory": 1, "product_domain_fit": 1, "timeline": 1,
        "archetype": "distributed_systems",
        "reasoning": "Strong technical match with clear senior scope.",
    })


def _make_scorer(minimal_config, mock_tracker):
    with patch("agents.scorer.get_active_llm"):
        return ScorerAgent(mock_tracker, minimal_config)


# ── tests ─────────────────────────────────────────────────────────────────────

def test_scorer_returns_valid_job_score_for_strong_match(
    minimal_config, mock_tracker, mock_llm_response
):
    with patch("agents.scorer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(_strong_match_json())
        mock_get_llm.return_value = mock_llm

        scorer = ScorerAgent(mock_tracker, minimal_config)
        job = {
            "company": "Razorpay", "title": "Senior Backend",
            "description": "Build distributed systems at scale.",
            "location": "Bengaluru", "url": "https://razorpay.com/jobs/1",
        }
        result = scorer.run("app-123", job)

    # base = 4+4+2+2+2+1+1+1 = 17, tier_bonus = 3 -> 20, capped at 13
    assert result.score == 13
    assert result.score <= 13
    assert result.grade == "A"
    assert result.archetype == "distributed_systems"
    assert result.tier_bonus == 3


def test_scorer_applies_gate_pass_when_role_fit_low(
    minimal_config, mock_tracker, mock_llm_response
):
    low_fit_json = json.dumps({
        "role_fit": 1, "skills_alignment": 4,
        "seniority_fit": 2, "salary_signal": 2, "interview_likelihood": 2,
        "growth_trajectory": 1, "product_domain_fit": 1, "timeline": 1,
        "archetype": "distributed_systems",
        "reasoning": "Role is frontend-heavy; candidate is backend specialist.",
    })
    with patch("agents.scorer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(low_fit_json)
        mock_get_llm.return_value = mock_llm

        scorer = ScorerAgent(mock_tracker, minimal_config)
        job = {
            "company": "Razorpay", "title": "Frontend Engineer",
            "description": "React and TypeScript focused role.",
            "location": "Bengaluru", "url": "x",
        }
        result = scorer.run("app-123", job)

    # base capped at 5 (role_fit < 2), tier_bonus 3 -> 8
    assert result.score <= 8


def test_scorer_tier_3_blacklist_scores_negative(
    minimal_config, mock_tracker, mock_llm_response
):
    """Blacklisted companies get -99 tier bonus, always grade F."""
    with patch("agents.scorer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(_strong_match_json())
        mock_get_llm.return_value = mock_llm

        scorer = ScorerAgent(mock_tracker, minimal_config)
        job = {
            "company": "Byju's", "title": "Senior Backend",
            "description": "Build learning platform at scale.",
            "location": "Bengaluru", "url": "x",
        }
        result = scorer.run("app-123", job)

    # total = 17 + (-99) = -82 -> score clamped to 0, grade F
    assert result.grade == "F"
    assert result.tier_bonus == -99
    assert result.score == 0


def test_scorer_grade_calculation_parametrised(minimal_config, mock_tracker):
    """Verify grade boundaries at 11, 9, 7, 5."""
    scorer = ScorerAgent.__new__(ScorerAgent)
    scorer.config = minimal_config

    test_cases = [
        (13, "A"), (11, "A"), (10, "B"), (9, "B"),
        (8, "C"), (7, "C"), (6, "D"), (5, "D"),
        (4, "F"), (0, "F"),
    ]
    for total, expected in test_cases:
        assert scorer._calculate_grade(total) == expected, (
            f"_calculate_grade({total}) should be '{expected}'"
        )


def test_scorer_retries_on_invalid_json(
    minimal_config, mock_tracker, mock_llm_response
):
    """On JSON decode error, retries up to 3 times."""
    valid_json = json.dumps({
        "role_fit": 3, "skills_alignment": 3, "seniority_fit": 2,
        "salary_signal": 1, "interview_likelihood": 1,
        "growth_trajectory": 1, "product_domain_fit": 0, "timeline": 0,
        "archetype": "distributed_systems",
        "reasoning": "Decent match across core dimensions.",
    })

    with patch("agents.scorer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = [
            mock_llm_response("not valid json"),
            mock_llm_response("still not json"),
            mock_llm_response(valid_json),
        ]
        mock_get_llm.return_value = mock_llm

        scorer = ScorerAgent(mock_tracker, minimal_config)
        job = {
            "company": "Razorpay", "title": "Senior Backend",
            "description": "...", "location": "Bengaluru", "url": "x",
        }
        result = scorer.run("app-123", job)

    assert mock_llm.complete.call_count == 3
    assert result.grade in ("A", "B", "C", "D", "F")
    assert isinstance(result, JobScore)


def test_scorer_raises_after_max_retries(
    minimal_config, mock_tracker, mock_llm_response
):
    with patch("agents.scorer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response("not json at all")
        mock_get_llm.return_value = mock_llm

        scorer = ScorerAgent(mock_tracker, minimal_config)
        job = {
            "company": "Razorpay", "title": "Senior Backend",
            "description": "...", "location": "x", "url": "x",
        }

        with pytest.raises(RuntimeError, match="failed after 3 retries"):
            scorer.run("app-123", job)

    assert mock_llm.complete.call_count == 3


# ── _strip_fences ─────────────────────────────────────────────────────────────

def test_strip_fences_removes_json_code_block():
    assert _strip_fences("```json\n{\"key\": 1}\n```") == '{"key": 1}'


def test_strip_fences_removes_plain_code_block():
    assert _strip_fences("```\n{\"key\": 1}\n```") == '{"key": 1}'


def test_strip_fences_passthrough_for_bare_json():
    raw = '{"key": 1}'
    assert _strip_fences(raw) == raw


def test_scorer_logs_token_counts(
    minimal_config, mock_tracker, mock_llm_response
):
    """@audited decorator must populate tokens_used from _last_llm_response."""
    with patch("agents.scorer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(_strong_match_json())
        mock_get_llm.return_value = mock_llm

        scorer = ScorerAgent(mock_tracker, minimal_config)
        scorer.run("app-123", {
            "company": "Razorpay", "title": "Senior Backend",
            "description": "...", "location": "Bengaluru", "url": "x",
        })

    log_kwargs = mock_tracker.log.call_args.kwargs
    assert log_kwargs["tokens_used"] == 150  # input_tokens=100 + output_tokens=50


def test_scorer_parses_fenced_json_response(
    minimal_config, mock_tracker, mock_llm_response
):
    """LLM wraps JSON in ```json fences — scorer must still parse it."""
    fenced = "```json\n" + _strong_match_json() + "\n```"
    with patch("agents.scorer.get_active_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(fenced)
        mock_get_llm.return_value = mock_llm

        scorer = ScorerAgent(mock_tracker, minimal_config)
        result = scorer.run("app-123", {
            "company": "Razorpay", "title": "Senior Backend",
            "description": "...", "location": "Bengaluru", "url": "x",
        })

    assert isinstance(result, JobScore)
    assert mock_llm.complete.call_count == 1

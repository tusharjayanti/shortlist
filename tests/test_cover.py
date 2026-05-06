import json
from unittest.mock import MagicMock, patch

import pytest

from agents.cover import CoverLetterAgent
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
    CoverLetter,
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
def mock_llm_response():
    def _make(text):
        r = MagicMock()
        r.text = text
        r.input_tokens = 100
        r.output_tokens = 50
        return r
    return _make


@pytest.fixture
def sample_corpus():
    return Corpus(
        name="Test User",
        roles=[
            CorpusRole(
                role_id="acme-senior-engineer",
                company="Acme Corp",
                title="Senior Engineer",
                bullets=[
                    CorpusBullet(
                        role_id="acme-senior-engineer",
                        bullet_id="built-data-pipeline",
                        title="Built data pipeline",
                        text="Built a scalable data pipeline processing 1M+ records daily.",
                    ),
                    CorpusBullet(
                        role_id="acme-senior-engineer",
                        bullet_id="migrated-microservices",
                        title="Migrated microservices",
                        text="Led migration of monolithic billing service into 4 microservices.",
                    ),
                ],
            ),
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


LONG_LETTER_TEXT = (
    "Building data infrastructure at scale is exactly the problem I "
    "have been solving for the last three years. At Acme Corp I "
    "designed and shipped a scalable data pipeline processing more "
    "than one million records daily, reducing overnight batch time "
    "from four hours to forty-five minutes through parallel "
    "execution and clean partitioning. I also led the migration of "
    "our monolithic billing service into four well-bounded "
    "microservices over six months, coordinating with three product "
    "teams and landing zero customer-facing incidents during the "
    "cutover window. The Senior Backend Engineer role at Razorpay "
    "sits at the intersection of these two strengths. Payments "
    "scale demands the same throughput discipline I applied to our "
    "overnight batch system, and the platform Razorpay is building "
    "requires the same cross-team coordination that the "
    "microservices migration demanded from me. I have spent the "
    "last several years moving from generalist backend engineering "
    "toward platform-shaped problems, and your engineering culture "
    "is exactly where I want to take that next step. I would "
    "welcome a conversation about how my experience at Acme maps "
    "directly to the systems your team is building today."
)


def _valid_payload(text: str = LONG_LETTER_TEXT) -> dict:
    return {
        "angle": (
            "Lead with data pipeline scale at Acme as proxy for "
            "Razorpay payments scale, frame as fintech_platform."
        ),
        "selected_proof_point_ids": [
            "built-data-pipeline",
            "migrated-microservices",
        ],
        "company_research_signals": ["10k+ TPS"],
        "text": text,
        "word_count": len(text.split()),
    }


@pytest.fixture
def valid_cover_json():
    return json.dumps(_valid_payload())


# ── tests ─────────────────────────────────────────────────────────────────────

def _patch_cover_deps(sample_corpus):
    """Common patch context: get_active_llm + parse_corpus."""
    return (
        patch("agents.cover.get_active_llm"),
        patch("agents.cover.parse_corpus", return_value=sample_corpus),
    )


def test_cover_letter_returns_valid_object_with_strategy(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_cover_json,
):
    with patch("agents.cover.get_active_llm") as mock_get_llm, \
         patch("agents.cover.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_cover_json)
        mock_get_llm.return_value = mock_llm

        agent = CoverLetterAgent(mock_tracker, minimal_config)
        result = agent.run("app-1", sample_job, "fintech_platform")

    assert isinstance(result, CoverLetter)
    assert "Razorpay" in result.text
    assert result.angle.startswith("Lead with")
    assert len(result.selected_proof_point_ids) == 2
    assert "10k+ TPS" in result.company_research_signals


def test_cover_letter_word_count_recalculated_server_side(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job,
):
    payload = _valid_payload()
    payload["word_count"] = 9999  # LLM lied
    bad_count_json = json.dumps(payload)

    with patch("agents.cover.get_active_llm") as mock_get_llm, \
         patch("agents.cover.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(bad_count_json)
        mock_get_llm.return_value = mock_llm

        agent = CoverLetterAgent(mock_tracker, minimal_config)
        result = agent.run("app-1", sample_job, "fintech_platform")

    assert result.word_count == len(LONG_LETTER_TEXT.split())
    assert result.word_count != 9999


def test_cover_letter_retries_when_company_name_missing(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_cover_json,
):
    no_company_text = LONG_LETTER_TEXT.replace("Razorpay", "the company")
    no_company_json = json.dumps(_valid_payload(text=no_company_text))

    with patch("agents.cover.get_active_llm") as mock_get_llm, \
         patch("agents.cover.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = [
            mock_llm_response(no_company_json),
            mock_llm_response(valid_cover_json),
        ]
        mock_get_llm.return_value = mock_llm

        agent = CoverLetterAgent(mock_tracker, minimal_config)
        result = agent.run("app-1", sample_job, "fintech_platform")

    assert mock_llm.complete.call_count == 2
    assert "Razorpay" in result.text


def test_cover_letter_retries_when_proof_point_id_invalid(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_cover_json,
):
    bad_id_payload = _valid_payload()
    bad_id_payload["selected_proof_point_ids"] = [
        "built-data-pipeline", "this-id-does-not-exist"
    ]
    bad_id_json = json.dumps(bad_id_payload)

    with patch("agents.cover.get_active_llm") as mock_get_llm, \
         patch("agents.cover.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = [
            mock_llm_response(bad_id_json),
            mock_llm_response(valid_cover_json),
        ]
        mock_get_llm.return_value = mock_llm

        agent = CoverLetterAgent(mock_tracker, minimal_config)
        result = agent.run("app-1", sample_job, "fintech_platform")

    assert mock_llm.complete.call_count == 2
    for bid in result.selected_proof_point_ids:
        assert sample_corpus.get_bullet(bid) is not None


def test_cover_letter_retries_when_proof_points_too_few(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_cover_json,
):
    too_few_payload = _valid_payload()
    too_few_payload["selected_proof_point_ids"] = ["built-data-pipeline"]
    too_few_json = json.dumps(too_few_payload)

    with patch("agents.cover.get_active_llm") as mock_get_llm, \
         patch("agents.cover.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = [
            mock_llm_response(too_few_json),
            mock_llm_response(valid_cover_json),
        ]
        mock_get_llm.return_value = mock_llm

        agent = CoverLetterAgent(mock_tracker, minimal_config)
        result = agent.run("app-1", sample_job, "fintech_platform")

    assert mock_llm.complete.call_count == 2
    assert len(result.selected_proof_point_ids) >= 2


def test_cover_letter_includes_corpus_in_prompt_with_bullet_ids(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_cover_json,
):
    with patch("agents.cover.get_active_llm") as mock_get_llm, \
         patch("agents.cover.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_cover_json)
        mock_get_llm.return_value = mock_llm

        agent = CoverLetterAgent(mock_tracker, minimal_config)
        agent.run("app-1", sample_job, "fintech_platform")

    user_message = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
    assert "[id: built-data-pipeline]" in user_message
    assert "[id: migrated-microservices]" in user_message
    assert "Acme Corp" in user_message


def test_cover_letter_includes_archetype_in_system_prompt(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_cover_json,
):
    with patch("agents.cover.get_active_llm") as mock_get_llm, \
         patch("agents.cover.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_cover_json)
        mock_get_llm.return_value = mock_llm

        agent = CoverLetterAgent(mock_tracker, minimal_config)
        agent.run("app-1", sample_job, "fintech_platform")

    system_prompt = mock_llm.complete.call_args.kwargs["system_prompt"]
    assert "fintech_platform" in system_prompt
    assert "payments correctness at scale" in system_prompt


def test_cover_letter_includes_feedback_in_prompt(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_cover_json,
):
    with patch("agents.cover.get_active_llm") as mock_get_llm, \
         patch("agents.cover.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_cover_json)
        mock_get_llm.return_value = mock_llm

        agent = CoverLetterAgent(mock_tracker, minimal_config)
        agent.run(
            "app-1", sample_job, "fintech_platform",
            feedback="open with the microservices migration instead",
        )

    user_message = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
    assert "open with the microservices migration instead" in user_message


def test_cover_letter_uses_temperature_0_4(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_cover_json,
):
    with patch("agents.cover.get_active_llm") as mock_get_llm, \
         patch("agents.cover.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_cover_json)
        mock_get_llm.return_value = mock_llm

        agent = CoverLetterAgent(mock_tracker, minimal_config)
        agent.run("app-1", sample_job, "fintech_platform")

    assert mock_llm.complete.call_args.kwargs["temperature"] == 0.4


def test_cover_letter_raises_after_max_retries(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job,
):
    with patch("agents.cover.get_active_llm") as mock_get_llm, \
         patch("agents.cover.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response("not json at all")
        mock_get_llm.return_value = mock_llm

        agent = CoverLetterAgent(mock_tracker, minimal_config)
        with pytest.raises(RuntimeError, match="failed after 3 retries"):
            agent.run("app-1", sample_job, "fintech_platform")

    assert mock_llm.complete.call_count == 3

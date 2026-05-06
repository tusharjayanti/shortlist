import json
from unittest.mock import MagicMock, patch

import pytest

from agents.networker import NetworkerAgent
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
    NetworkingMessages,
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
                        bullet_id="data-pipeline",
                        title="Data pipeline",
                        text="Built scalable pipeline processing 1M records daily.",
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


DM_TEXT = (
    "Hi {{recipient_name}}, I noticed Razorpay's Senior "
    "Backend Engineer role and the focus on idempotent "
    "payment processing at scale. I have built financial "
    "systems handling 10k+ daily transactions with strict "
    "correctness guarantees. Would you be open to a quick "
    "10-minute call to learn more about the team?"
)

EMAIL_TEXT = (
    "Hi {{recipient_name}},\n\n"
    "I came across the Senior Backend Engineer role at "
    "Razorpay, and the requirements around idempotent APIs "
    "at ten thousand TPS caught my attention. Payments "
    "correctness at that scale is the kind of problem I have "
    "been deliberately positioning my career toward, and "
    "your job description reads like a checklist of the "
    "things I have been doing.\n\n"
    "At Acme Corp I built a scalable data pipeline processing "
    "more than one million records daily, reducing overnight "
    "batch time from four hours to forty-five minutes through "
    "parallel execution and clean partitioning. Earlier I led "
    "the migration of a monolithic billing service into four "
    "well-bounded microservices over six months, coordinating "
    "across three product teams and shipping zero customer-"
    "facing incidents during the cutover window. Both of those "
    "projects sat on the seam between throughput and "
    "correctness, which seems to be where Razorpay lives "
    "every day.\n\n"
    "I would value fifteen minutes of your time to learn how "
    "your team thinks about the trade-off between reliability "
    "and velocity, and how senior engineers there spend their "
    "first six months. Would next Tuesday or Wednesday morning "
    "work for you, or is there a better window in the next "
    "two weeks?"
)


def _valid_payload(
    dm: str = DM_TEXT,
    email: str = EMAIL_TEXT,
    proof_ids=None,
    placeholders=None,
) -> dict:
    return {
        "angle": (
            "Lead with idempotent pipeline experience as direct "
            "mapping to Razorpay payments correctness."
        ),
        "selected_proof_point_ids": proof_ids or ["data-pipeline"],
        "linkedin_dm": dm,
        "linkedin_dm_word_count": len(dm.split()),
        "cold_email_subject": "Senior Backend Engineer at Razorpay - 15 minutes?",
        "cold_email_body": email,
        "cold_email_word_count": len(email.split()),
        "placeholders_used": (
            placeholders if placeholders is not None
            else ["{{recipient_name}}"]
        ),
    }


@pytest.fixture
def valid_networker_json():
    return json.dumps(_valid_payload())


# ── tests ─────────────────────────────────────────────────────────────────────

def test_networker_returns_valid_messages(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_networker_json,
):
    with patch("agents.networker.get_active_llm") as mock_get_llm, \
         patch("agents.networker.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_networker_json)
        mock_get_llm.return_value = mock_llm

        agent = NetworkerAgent(mock_tracker, minimal_config)
        result = agent.run("app-1", sample_job, "fintech_platform")

    assert isinstance(result, NetworkingMessages)
    assert "Razorpay" in result.linkedin_dm
    assert "Razorpay" in result.cold_email_body
    assert result.angle.startswith("Lead with")
    assert result.selected_proof_point_ids == ["data-pipeline"]


def test_networker_recalculates_word_counts_server_side(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job,
):
    payload = _valid_payload()
    payload["linkedin_dm_word_count"] = 9999
    payload["cold_email_word_count"] = 9999
    bad_json = json.dumps(payload)

    with patch("agents.networker.get_active_llm") as mock_get_llm, \
         patch("agents.networker.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(bad_json)
        mock_get_llm.return_value = mock_llm

        agent = NetworkerAgent(mock_tracker, minimal_config)
        result = agent.run("app-1", sample_job, "fintech_platform")

    assert result.linkedin_dm_word_count == len(DM_TEXT.split())
    assert result.cold_email_word_count == len(EMAIL_TEXT.split())
    assert result.linkedin_dm_word_count != 9999


def test_networker_retries_when_company_missing_from_dm(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_networker_json,
):
    no_company_dm = DM_TEXT.replace("Razorpay", "the company")
    bad_json = json.dumps(_valid_payload(dm=no_company_dm))

    with patch("agents.networker.get_active_llm") as mock_get_llm, \
         patch("agents.networker.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = [
            mock_llm_response(bad_json),
            mock_llm_response(valid_networker_json),
        ]
        mock_get_llm.return_value = mock_llm

        agent = NetworkerAgent(mock_tracker, minimal_config)
        result = agent.run("app-1", sample_job, "fintech_platform")

    assert mock_llm.complete.call_count == 2
    assert "Razorpay" in result.linkedin_dm


def test_networker_retries_when_company_missing_from_email(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_networker_json,
):
    no_company_email = EMAIL_TEXT.replace("Razorpay", "the company")
    bad_payload = _valid_payload(email=no_company_email)
    bad_payload["cold_email_subject"] = "Senior Backend Engineer - 15 minutes?"
    bad_json = json.dumps(bad_payload)

    with patch("agents.networker.get_active_llm") as mock_get_llm, \
         patch("agents.networker.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = [
            mock_llm_response(bad_json),
            mock_llm_response(valid_networker_json),
        ]
        mock_get_llm.return_value = mock_llm

        agent = NetworkerAgent(mock_tracker, minimal_config)
        result = agent.run("app-1", sample_job, "fintech_platform")

    assert mock_llm.complete.call_count == 2
    assert "Razorpay" in result.cold_email_body


def test_networker_retries_when_proof_point_id_invalid(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_networker_json,
):
    bad_payload = _valid_payload(proof_ids=["fake-id"])
    bad_json = json.dumps(bad_payload)

    with patch("agents.networker.get_active_llm") as mock_get_llm, \
         patch("agents.networker.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.side_effect = [
            mock_llm_response(bad_json),
            mock_llm_response(valid_networker_json),
        ]
        mock_get_llm.return_value = mock_llm

        agent = NetworkerAgent(mock_tracker, minimal_config)
        result = agent.run("app-1", sample_job, "fintech_platform")

    assert mock_llm.complete.call_count == 2
    for bid in result.selected_proof_point_ids:
        assert sample_corpus.get_bullet(bid) is not None


def test_networker_extracts_placeholders_from_messages(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job,
):
    """LLM omits placeholders_used; agent auto-extracts from message text."""
    payload = _valid_payload()
    del payload["placeholders_used"]
    no_placeholders_json = json.dumps(payload)

    with patch("agents.networker.get_active_llm") as mock_get_llm, \
         patch("agents.networker.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(no_placeholders_json)
        mock_get_llm.return_value = mock_llm

        agent = NetworkerAgent(mock_tracker, minimal_config)
        result = agent.run("app-1", sample_job, "fintech_platform")

    assert "{{recipient_name}}" in result.placeholders_used


def test_networker_includes_archetype_in_system_prompt(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_networker_json,
):
    with patch("agents.networker.get_active_llm") as mock_get_llm, \
         patch("agents.networker.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_networker_json)
        mock_get_llm.return_value = mock_llm

        agent = NetworkerAgent(mock_tracker, minimal_config)
        agent.run("app-1", sample_job, "fintech_platform")

    system_prompt = mock_llm.complete.call_args.kwargs["system_prompt"]
    assert "fintech_platform" in system_prompt
    assert "payments correctness at scale" in system_prompt


def test_networker_includes_corpus_with_bullet_ids(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_networker_json,
):
    with patch("agents.networker.get_active_llm") as mock_get_llm, \
         patch("agents.networker.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_networker_json)
        mock_get_llm.return_value = mock_llm

        agent = NetworkerAgent(mock_tracker, minimal_config)
        agent.run("app-1", sample_job, "fintech_platform")

    user_message = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
    assert "[id: data-pipeline]" in user_message
    assert "Acme Corp" in user_message


def test_networker_includes_feedback_in_prompt(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_networker_json,
):
    with patch("agents.networker.get_active_llm") as mock_get_llm, \
         patch("agents.networker.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_networker_json)
        mock_get_llm.return_value = mock_llm

        agent = NetworkerAgent(mock_tracker, minimal_config)
        agent.run(
            "app-1", sample_job, "fintech_platform",
            feedback="lead with the microservices migration instead",
        )

    user_message = mock_llm.complete.call_args.kwargs["messages"][0]["content"]
    assert "lead with the microservices migration instead" in user_message


def test_networker_uses_temperature_0_4(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job, valid_networker_json,
):
    with patch("agents.networker.get_active_llm") as mock_get_llm, \
         patch("agents.networker.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response(valid_networker_json)
        mock_get_llm.return_value = mock_llm

        agent = NetworkerAgent(mock_tracker, minimal_config)
        agent.run("app-1", sample_job, "fintech_platform")

    assert mock_llm.complete.call_args.kwargs["temperature"] == 0.4


def test_networker_raises_after_max_retries(
    minimal_config, mock_tracker, mock_llm_response,
    sample_corpus, sample_job,
):
    with patch("agents.networker.get_active_llm") as mock_get_llm, \
         patch("agents.networker.parse_corpus", return_value=sample_corpus):
        mock_llm = MagicMock()
        mock_llm.complete.return_value = mock_llm_response("not json at all")
        mock_get_llm.return_value = mock_llm

        agent = NetworkerAgent(mock_tracker, minimal_config)
        with pytest.raises(RuntimeError, match="failed after 3 retries"):
            agent.run("app-1", sample_job, "fintech_platform")

    assert mock_llm.complete.call_count == 3

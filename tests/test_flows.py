from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from flows.audit import AuditFlow
from flows.pipeline import PipelineFlow
from flows.proactive import ProactiveFlow
from flows.reactive import ReactiveFlow
from flows.status import StatusFlow
from tools.config_loader import (
    ATSConfig,
    ArchetypeConfig,
    CandidateConfig,
    CompaniesConfig,
    CompanyTier,
    Config,
    LLMConfig,
    LocationConfig,
    ScoringConfig,
    ScrapingConfig,
    SeniorityConfig,
    SeniorityLevel,
    SourcesConfig,
    StartupInference,
)
from tools.schemas import (
    CoverLetter,
    JobScore,
    NetworkingMessages,
    PrioritizedEdit,
    ReviewResult,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def cfg():
    return Config(
        llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-6"),
        candidate=CandidateConfig(
            name="Test Engineer",
            experience_years=7,
            location=LocationConfig(primary="Bengaluru", aliases=["Bengaluru"]),
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
                senior_signals=["lead"], mid_signals=["build"],
                junior_signals=["learn"],
            ),
        ),
        companies=CompaniesConfig(
            big_tech={
                "tier_1": CompanyTier(
                    score_bonus=3, reason="Top",
                    names=["Razorpay"],
                ),
            },
            startups={"min_funding": "Series A"},
        ),
        scoring=ScoringConfig(minimum_score=7, weights={"role_fit": 4}),
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
    t = MagicMock()
    t.create_application.return_value = "app-1"
    t.is_url_seen.return_value = False
    t.is_seen_url.return_value = False
    return t


def _high_score(archetype="distributed_systems", score=10) -> JobScore:
    return JobScore(
        score=score, grade="B",
        role_fit=4, skills_alignment=4,
        seniority_fit=2, salary_signal=2,
        interview_likelihood=2, growth_trajectory=1,
        product_domain_fit=1, timeline=1,
        tier_bonus=0, archetype=archetype,
        reasoning="Strong match across dimensions.",
    )


def _low_score() -> JobScore:
    return JobScore(
        score=3, grade="F",
        role_fit=1, skills_alignment=1,
        seniority_fit=0, salary_signal=0,
        interview_likelihood=0, growth_trajectory=0,
        product_domain_fit=0, timeline=0,
        tier_bonus=1, archetype="distributed_systems",
        reasoning="Weak match across dimensions.",
    )


def _review() -> ReviewResult:
    return ReviewResult(
        verdict="Strong Fit", overall_confidence=0.9,
        strengths=["x"], gaps=["y"], missing_keywords=["z"],
        strategic_angle="Lead with backend depth.",
        prioritized_edits=[PrioritizedEdit(
            priority="high", change="rewrite", rationale="why",
        )],
    )


def _cover() -> CoverLetter:
    return CoverLetter(
        text="Razorpay letter text. " * 30,
        word_count=180,
        angle="Lead with backend depth as proxy for payments scale.",
        selected_proof_point_ids=["a", "b"],
        company_research_signals=["10k TPS"],
    )


def _networking() -> NetworkingMessages:
    return NetworkingMessages(
        linkedin_dm=(
            "Hi {{recipient_name}}, I noticed Razorpay's role and "
            "wanted to connect about backend systems. Would you have "
            "10 minutes this week to chat?"
        ),
        linkedin_dm_word_count=30,
        cold_email_subject="Razorpay Senior Backend - 15 minutes?",
        cold_email_body="Hi {{recipient_name}},\n\n" + "Razorpay outreach. " * 60,
        cold_email_word_count=180,
        angle="Lead with idempotent payment systems experience.",
        selected_proof_point_ids=["a"],
        placeholders_used=["{{recipient_name}}"],
    )


@pytest.fixture
def reactive_patches():
    """Patch every external dependency of ReactiveFlow."""
    with ExitStack() as stack:
        p = {
            "ScorerAgent": stack.enter_context(
                patch("flows.reactive.ScorerAgent")),
            "ReviewerAgent": stack.enter_context(
                patch("flows.reactive.ReviewerAgent")),
            "TailorAgent": stack.enter_context(
                patch("flows.reactive.TailorAgent")),
            "CoverLetterAgent": stack.enter_context(
                patch("flows.reactive.CoverLetterAgent")),
            "NetworkerAgent": stack.enter_context(
                patch("flows.reactive.NetworkerAgent")),
            "ReviewCoordinator": stack.enter_context(
                patch("flows.reactive.ReviewCoordinator")),
            "fetch_job": stack.enter_context(
                patch("flows.reactive.fetch_job")),
            "read_resume": stack.enter_context(
                patch("flows.reactive.read_resume")),
            "compile_pdf": stack.enter_context(
                patch("flows.reactive.compile_pdf")),
            "open_job_page": stack.enter_context(
                patch("flows.reactive.open_job_page")),
            "webbrowser": stack.enter_context(
                patch("flows.reactive.webbrowser")),
            "Prompt": stack.enter_context(
                patch("flows.reactive.Prompt")),
        }
        # Sensible defaults
        p["fetch_job"].return_value = {
            "title": "Senior Backend",
            "description": "Senior backend engineer role description. " * 30,
            "url": "https://razorpay.com/jobs/1",
            "gated": False,
            "blocked": False,
        }
        p["read_resume"].return_value = "resume tex content"
        p["compile_pdf"].return_value = "/tmp/r.pdf"
        p["ScorerAgent"].return_value.run.return_value = _high_score()
        p["ReviewerAgent"].return_value.run.return_value = _review()
        p["ReviewCoordinator"].return_value.run.return_value = {
            "resume_path": "/tmp/r.tex",
            "cover_letter": _cover(),
            "networking": _networking(),
            "aborted": False,
        }
        yield p


# ── ReactiveFlow ──────────────────────────────────────────────────────────────

def test_reactive_flow_url_path_runs_full_pipeline(
    cfg, mock_tracker, reactive_patches,
):
    p = reactive_patches
    # Prompts: title, company, location, proceed=y
    p["Prompt"].ask.side_effect = ["Senior Backend", "Razorpay", "Bengaluru", "y"]

    flow = ReactiveFlow(mock_tracker, cfg)
    result = flow.run("https://razorpay.com/jobs/1")

    assert result["status"] == "completed"
    assert p["fetch_job"].call_count == 1
    assert p["ScorerAgent"].return_value.run.call_count == 1
    assert p["ReviewerAgent"].return_value.run.call_count == 1
    assert p["ReviewCoordinator"].return_value.run.call_count == 1
    assert p["compile_pdf"].call_count == 1
    mock_tracker.mark_url_seen.assert_called_once_with("https://razorpay.com/jobs/1")
    # Final status update to "approved"
    statuses = [
        c.kwargs.get("status") or (c.args[1] if len(c.args) > 1 else None)
        for c in mock_tracker.update_application_status.call_args_list
    ]
    assert "approved" in statuses


def test_reactive_flow_pasted_text_path_runs_full_pipeline(
    cfg, mock_tracker, reactive_patches,
):
    p = reactive_patches
    p["Prompt"].ask.side_effect = ["Senior Backend", "Razorpay", "Bengaluru", "y"]

    flow = ReactiveFlow(mock_tracker, cfg)
    result = flow.run("This is a pasted job description with payments and Kafka.")

    assert result["status"] == "completed"
    # No scrape on pasted-text path
    assert p["fetch_job"].call_count == 0
    assert p["ScorerAgent"].return_value.run.call_count == 1


def test_reactive_flow_below_threshold_skips_pipeline(
    cfg, mock_tracker, reactive_patches,
):
    p = reactive_patches
    p["ScorerAgent"].return_value.run.return_value = _low_score()
    # Only the 3 input prompts; no proceed prompt because of early return
    p["Prompt"].ask.side_effect = ["Senior Backend", "Razorpay", "Bengaluru"]

    flow = ReactiveFlow(mock_tracker, cfg)
    result = flow.run("https://razorpay.com/jobs/1")

    assert result["status"] == "scored_below_threshold"
    assert p["ReviewerAgent"].return_value.run.call_count == 0
    assert p["ReviewCoordinator"].return_value.run.call_count == 0
    assert p["compile_pdf"].call_count == 0


def test_reactive_flow_handles_duplicate_url(cfg, mock_tracker, reactive_patches):
    mock_tracker.is_url_seen.return_value = True

    flow = ReactiveFlow(mock_tracker, cfg)
    result = flow.run("https://razorpay.com/jobs/1")

    assert result["status"] == "duplicate"
    p = reactive_patches
    assert p["fetch_job"].call_count == 0
    assert p["ScorerAgent"].return_value.run.call_count == 0
    mock_tracker.create_application.assert_not_called()


def test_reactive_flow_user_skips_after_score(cfg, mock_tracker, reactive_patches):
    p = reactive_patches
    # Title, company, location, proceed=n
    p["Prompt"].ask.side_effect = ["Senior Backend", "Razorpay", "Bengaluru", "n"]

    flow = ReactiveFlow(mock_tracker, cfg)
    result = flow.run("https://razorpay.com/jobs/1")

    assert result["status"] == "user_skipped"
    assert p["ReviewerAgent"].return_value.run.call_count == 0
    assert p["compile_pdf"].call_count == 0


def test_reactive_flow_aborted_coordinator_no_pdf(
    cfg, mock_tracker, reactive_patches,
):
    p = reactive_patches
    p["ReviewCoordinator"].return_value.run.return_value = {
        "resume_path": None, "cover_letter": None,
        "networking": None, "aborted": True,
    }
    p["Prompt"].ask.side_effect = ["Senior Backend", "Razorpay", "Bengaluru", "y"]

    flow = ReactiveFlow(mock_tracker, cfg)
    result = flow.run("https://razorpay.com/jobs/1")

    assert result["status"] == "aborted"
    assert p["compile_pdf"].call_count == 0


# ── ProactiveFlow ─────────────────────────────────────────────────────────────

@pytest.fixture
def proactive_patches():
    with ExitStack() as stack:
        p = {
            "ScorerAgent": stack.enter_context(
                patch("flows.proactive.ScorerAgent")),
            "FinderAgent": stack.enter_context(
                patch("flows.proactive.FinderAgent")),
            "ReactiveFlow": stack.enter_context(
                patch("flows.proactive.ReactiveFlow")),
            "Prompt": stack.enter_context(patch("flows.proactive.Prompt")),
        }
        p["ScorerAgent"].return_value.run.return_value = _high_score()
        p["ReactiveFlow"].return_value.run.return_value = {"status": "completed"}
        yield p


def _job(company: str, title: str = "Senior Backend") -> dict:
    return {
        "title": title, "company": company,
        "url": f"https://{company.lower().replace(' ', '')}.com/job",
        "description": f"Job at {company}",
        "location": "Bengaluru",
    }


def test_proactive_flow_no_jobs_short_circuits(cfg, mock_tracker, proactive_patches):
    p = proactive_patches
    p["FinderAgent"].return_value.run.return_value = []

    flow = ProactiveFlow(mock_tracker, cfg)
    result = flow.run()

    assert result["status"] == "no_jobs"
    assert p["ScorerAgent"].return_value.run.call_count == 0


def test_proactive_flow_below_threshold_short_circuits(
    cfg, mock_tracker, proactive_patches,
):
    p = proactive_patches
    p["FinderAgent"].return_value.run.return_value = [_job("Co")]
    p["ScorerAgent"].return_value.run.return_value = _low_score()

    flow = ProactiveFlow(mock_tracker, cfg)
    result = flow.run()

    assert result["status"] == "no_shortlist"
    assert result["jobs_scored"] == 1
    assert result["shortlist_size"] == 0
    assert p["ReactiveFlow"].return_value.run.call_count == 0


def test_proactive_flow_user_picks_subset(cfg, mock_tracker, proactive_patches):
    p = proactive_patches
    p["FinderAgent"].return_value.run.return_value = [
        _job("A"), _job("B"), _job("C"),
    ]
    p["Prompt"].ask.return_value = "0,2"

    flow = ProactiveFlow(mock_tracker, cfg)
    result = flow.run()

    assert result["status"] == "ok"
    assert p["ReactiveFlow"].return_value.run.call_count == 2


def test_proactive_flow_user_picks_all(cfg, mock_tracker, proactive_patches):
    p = proactive_patches
    p["FinderAgent"].return_value.run.return_value = [_job("A"), _job("B")]
    p["Prompt"].ask.return_value = "all"

    flow = ProactiveFlow(mock_tracker, cfg)
    result = flow.run()

    assert result["status"] == "ok"
    assert p["ReactiveFlow"].return_value.run.call_count == 2


def test_proactive_flow_user_picks_none(cfg, mock_tracker, proactive_patches):
    p = proactive_patches
    p["FinderAgent"].return_value.run.return_value = [_job("A"), _job("B")]
    p["Prompt"].ask.return_value = "none"

    flow = ProactiveFlow(mock_tracker, cfg)
    result = flow.run()

    assert result["status"] == "user_skipped"
    assert result["shortlist_size"] == 2
    assert p["ReactiveFlow"].return_value.run.call_count == 0


# ── StatusFlow ────────────────────────────────────────────────────────────────

def test_status_flow_funnel_with_no_apps(cfg, mock_tracker):
    mock_tracker.get_status_counts.return_value = {}
    flow = StatusFlow(mock_tracker, cfg)
    result = flow.funnel()
    assert result["total"] == 0


def test_status_flow_grade_distribution(cfg, mock_tracker):
    mock_tracker.get_grade_counts.return_value = {"A": 2, "B": 5, "C": 3}
    flow = StatusFlow(mock_tracker, cfg)
    result = flow.grade_distribution()
    assert result == {"A": 2, "B": 5, "C": 3}


def test_status_flow_cost_report_aggregates_by_agent(cfg, mock_tracker):
    mock_tracker.get_token_usage_by_agent.return_value = {
        "scorer": {"calls": 10, "total_tokens": 100_000},
        "reviewer": {"calls": 5, "total_tokens": 50_000},
        "tailor": {"calls": 2, "total_tokens": 200_000},
    }
    flow = StatusFlow(mock_tracker, cfg)
    result = flow.cost_report()

    assert result["by_agent"] == {
        "scorer": {"calls": 10, "total_tokens": 100_000},
        "reviewer": {"calls": 5, "total_tokens": 50_000},
        "tailor": {"calls": 2, "total_tokens": 200_000},
    }
    # Total tokens 350k * blended $6.6/M ≈ $2.31
    assert result["total_cost"] == pytest.approx(0.350 * 6.6, rel=1e-3)


# ── AuditFlow ─────────────────────────────────────────────────────────────────

def test_audit_flow_shows_logs_for_app(cfg, mock_tracker):
    mock_tracker.get_audit_logs_by_app.return_value = [
        {
            "timestamp": "2026-05-07 10:00:00", "agent": "scorer",
            "action": "score_job", "tokens_used": 150,
            "latency_ms": 1200, "success": True,
        },
        {
            "timestamp": "2026-05-07 10:01:00", "agent": "reviewer",
            "action": "analyze_fit", "tokens_used": 800,
            "latency_ms": 3400, "success": True,
        },
    ]
    mock_tracker.get_application.return_value = {
        "company": "Razorpay", "role": "Senior Backend", "status": "approved",
    }

    flow = AuditFlow(mock_tracker, cfg)
    logs = flow.show("app-1")

    assert len(logs) == 2
    mock_tracker.get_audit_logs_by_app.assert_called_once_with("app-1")


def test_audit_flow_handles_missing_app(cfg, mock_tracker):
    mock_tracker.get_audit_logs_by_app.return_value = []

    flow = AuditFlow(mock_tracker, cfg)
    logs = flow.show("nonexistent")

    assert logs == []
    mock_tracker.get_application.assert_not_called()


# ── PipelineFlow ──────────────────────────────────────────────────────────────

def test_pipeline_flow_resumes_existing_app(cfg, mock_tracker):
    mock_tracker.get_application.return_value = {
        "id": "app-1", "company": "Razorpay", "role": "Senior Backend",
        "status": "scored", "job_url": "https://razorpay.com/jobs/1",
    }

    with patch("flows.pipeline.ReactiveFlow") as MockReactive:
        MockReactive.return_value.run.return_value = {"status": "completed"}
        flow = PipelineFlow(mock_tracker, cfg)
        result = flow.run("app-1")

    assert result["status"] == "completed"
    MockReactive.return_value.run.assert_called_once_with(
        "https://razorpay.com/jobs/1",
    )


def test_pipeline_flow_handles_missing_app(cfg, mock_tracker):
    mock_tracker.get_application.return_value = None

    with patch("flows.pipeline.ReactiveFlow") as MockReactive:
        flow = PipelineFlow(mock_tracker, cfg)
        result = flow.run("nonexistent")

    assert result["status"] == "not_found"
    MockReactive.return_value.run.assert_not_called()

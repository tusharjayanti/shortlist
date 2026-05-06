from pathlib import Path

import pytest

from tools.corpus import parse_corpus
from tools.prompts import load_prompt
from tools.schemas import Corpus

FIXTURE = Path(__file__).parent / "fixtures" / "test_experience.md"


@pytest.fixture
def corpus():
    return parse_corpus(str(FIXTURE))


# ── parser ────────────────────────────────────────────────────────────────────

def test_parse_corpus_extracts_name(corpus):
    assert corpus.name == "Test User"


def test_parse_corpus_finds_two_roles(corpus):
    assert len(corpus.roles) == 2
    companies = [r.company for r in corpus.roles]
    assert companies == ["Acme Corp", "Beta Inc"]


def test_parse_corpus_extracts_dates_and_stack(corpus):
    acme = corpus.roles[0]
    assert acme.dates == "2023 - Present"
    assert acme.tech_stack == ["Python", "PostgreSQL", "AWS"]


def test_parse_corpus_finds_personal_projects(corpus):
    assert len(corpus.projects) == 1
    assert corpus.projects[0].title == "Open source library"


def test_parse_corpus_finds_education(corpus):
    assert len(corpus.education) >= 1
    assert "Master of Science" in corpus.education[0]


# ── corpus methods ────────────────────────────────────────────────────────────

def test_get_bullet_by_id_in_role(corpus):
    bullet = corpus.get_bullet("built-data-pipeline")
    assert bullet is not None
    assert bullet.title == "Built data pipeline"
    assert "Apache Airflow" in bullet.text


def test_get_bullet_by_id_in_projects(corpus):
    bullet = corpus.get_bullet("open-source-library")
    assert bullet is not None
    assert bullet.role_id == "personal-projects"


def test_get_role_by_id(corpus):
    role = corpus.get_role("acme-corp-senior-engineer")
    assert role is not None
    assert role.company == "Acme Corp"


def test_find_role_by_company_case_insensitive(corpus):
    role = corpus.find_role_by_company("acme corp")
    assert role is not None
    assert role.title == "Senior Engineer"
    assert corpus.find_role_by_company("ACME CORP") is not None
    assert corpus.find_role_by_company("nonexistent") is None


def test_corpus_round_trips_through_pydantic(corpus):
    dumped = corpus.model_dump()
    rebuilt = Corpus(**dumped)
    assert rebuilt == corpus


# ── prompt loader ─────────────────────────────────────────────────────────────

def test_load_prompt_returns_content():
    text = load_prompt("scorer")
    assert isinstance(text, str)
    assert len(text) > 100
    assert "{name}" in text  # placeholder preserved for str.format()


def test_load_prompt_raises_for_missing_file():
    with pytest.raises(FileNotFoundError, match="Prompt file not found"):
        load_prompt("does_not_exist")


def test_agent_loads_prompt_from_disk_not_constant():
    """Agents must read prompts from prompts/*.md, not module-level constants."""
    import agents.scorer as scorer_mod
    import agents.reviewer as reviewer_mod
    import agents.tailor as tailor_mod

    assert not hasattr(scorer_mod, "SYSTEM_PROMPT")
    assert not hasattr(reviewer_mod, "SYSTEM_PROMPT")
    assert not hasattr(tailor_mod, "SYSTEM_PROMPT")

    assert load_prompt("scorer")
    assert load_prompt("reviewer")
    assert load_prompt("tailor")

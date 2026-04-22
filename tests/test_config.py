import textwrap
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from tools.config_loader import Config, load_config
from tools.schemas import JobScore

FIXTURE = Path(__file__).parent / "fixtures" / "test_config.yaml"


def test_load_config_returns_valid_config():
    cfg = load_config(str(FIXTURE))
    assert isinstance(cfg, Config)
    assert cfg.candidate.name == "Test Engineer"
    assert cfg.llm.provider == "anthropic"


def test_missing_config_raises_file_not_found_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config(str(tmp_path / "nonexistent.yaml"))


def test_malformed_yaml_raises_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("key: [unclosed bracket")
    with pytest.raises(yaml.YAMLError):
        load_config(str(bad))


def test_invalid_field_raises_value_error(tmp_path):
    cfg_path = tmp_path / "bad_schema.yaml"
    data = yaml.safe_load(FIXTURE.read_text())
    data["llm"]["provider"] = "unknown_provider"
    cfg_path.write_text(yaml.dump(data))
    with pytest.raises(ValueError, match="Config validation failed"):
        load_config(str(cfg_path))


def test_invalid_score_raises_validation_error():
    with pytest.raises(ValidationError):
        JobScore(
            score=99,
            grade="A",
            role_fit=4,
            skills_alignment=4,
            seniority_fit=2,
            salary_signal=2,
            interview_likelihood=2,
            growth_trajectory=1,
            product_domain_fit=1,
            timeline=1,
            tier_bonus=3,
            archetype="distributed_systems",
            reasoning="Excellent match for the role requirements.",
        )


def test_get_company_tier_known():
    cfg = load_config(str(FIXTURE))
    assert cfg.get_company_tier("Google") == 1
    assert cfg.get_company_tier("Atlassian") == 2
    assert cfg.get_company_tier("Sketchy Corp") == 3


def test_get_company_tier_case_insensitive():
    cfg = load_config(str(FIXTURE))
    assert cfg.get_company_tier("google") == 1
    assert cfg.get_company_tier("STRIPE") == 1
    assert cfg.get_company_tier("datadog") == 2


def test_get_company_tier_unknown():
    cfg = load_config(str(FIXTURE))
    assert cfg.get_company_tier("Some Random Startup") == 0


def test_is_blacklisted_tier_3():
    cfg = load_config(str(FIXTURE))
    assert cfg.is_blacklisted("Sketchy Corp") is True
    assert cfg.is_blacklisted("Google") is False
    assert cfg.is_blacklisted("Nobody Inc") is False


def test_matches_location_true():
    cfg = load_config(str(FIXTURE))
    assert cfg.matches_location("Bengaluru, Karnataka") is True


def test_matches_location_case_insensitive():
    cfg = load_config(str(FIXTURE))
    assert cfg.matches_location("BANGALORE, India") is True
    assert cfg.matches_location("bengaluru, karnataka") is True


def test_matches_location_false():
    cfg = load_config(str(FIXTURE))
    assert cfg.matches_location("Mumbai, Maharashtra") is False

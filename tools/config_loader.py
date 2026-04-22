from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ValidationError


class LLMConfig(BaseModel):
    provider: Literal["anthropic", "gemini", "openai"]
    model: str
    max_tokens: int = 4096
    temperature: float = 0.3


class LocationConfig(BaseModel):
    primary: str
    aliases: list[str]


class CandidateConfig(BaseModel):
    name: str
    experience_years: int
    location: LocationConfig
    min_salary_lpa: int
    max_salary_lpa: int
    roles: list[str]
    languages: list[str]
    backend: list[str] = []
    databases: list[str] = []
    cloud_devops: list[str] = []
    data: list[str] = []
    ai_tools: list[str] = []
    strengths: list[str] = []


class ArchetypeConfig(BaseModel):
    lead_with: str
    proof_points: list[str]


class SeniorityLevel(BaseModel):
    canonical: str
    score_penalty: int = 0
    score_bonus: int = 0
    patterns: list[str]


class StartupInference(BaseModel):
    senior_signals: list[str]
    mid_signals: list[str]
    junior_signals: list[str]


class SeniorityConfig(BaseModel):
    target_level: str
    levels: dict[str, SeniorityLevel]
    startup_inference: StartupInference


class CompanyTier(BaseModel):
    score_bonus: int
    reason: str
    names: list[str]


class CompaniesConfig(BaseModel):
    big_tech: dict[str, CompanyTier]
    startups: dict[str, Any]


class ScoringConfig(BaseModel):
    minimum_score: int
    weights: dict[str, int]


class ATSConfig(BaseModel):
    greenhouse: list[str] = []
    ashby: list[str] = []
    lever: list[str] = []


class ScrapingConfig(BaseModel):
    allowed_domains: list[str]
    delay_seconds: float = 2.0
    min_delay: float = 0.5
    max_delay: float = 8.0
    user_agents: list[str]


class SourcesConfig(BaseModel):
    ats: ATSConfig
    wellfound: dict[str, Any] = {}
    rss: list[str] = []
    scraping: ScrapingConfig


class Config(BaseModel):
    llm: LLMConfig
    candidate: CandidateConfig
    archetypes: dict[str, ArchetypeConfig]
    seniority: SeniorityConfig
    companies: CompaniesConfig
    scoring: ScoringConfig
    sources: SourcesConfig

    def _tier_entry_for(self, company_name: str) -> tuple[str, CompanyTier] | None:
        name_lower = company_name.lower()
        for tier_key, tier in self.companies.big_tech.items():
            if any(n.lower() == name_lower for n in tier.names):
                return tier_key, tier
        return None

    def get_company_tier(self, company_name: str) -> int:
        entry = self._tier_entry_for(company_name)
        if entry is None:
            return 0
        tier_key, _ = entry
        try:
            return int(tier_key.split("_")[-1])
        except ValueError:
            return 0

    def is_blacklisted(self, company_name: str) -> bool:
        return self.get_company_tier(company_name) == 3

    def get_tier_bonus(self, company_name: str) -> int:
        entry = self._tier_entry_for(company_name)
        return entry[1].score_bonus if entry else 0

    def matches_location(self, text: str) -> bool:
        text_lower = text.lower()
        return any(alias.lower() in text_lower for alias in self.candidate.location.aliases)


def load_config(path: str = "config.yaml") -> Config:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with config_path.open() as f:
        data = yaml.safe_load(f)
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        first_loc = " -> ".join(str(part) for part in e.errors()[0]["loc"]) if e.errors() else "unknown"
        raise ValueError(f"Config validation failed at '{first_loc}': {e.errors()[0]['msg']}") from e

from typing import Literal

from pydantic import BaseModel, Field


class JobScore(BaseModel):
    score: int = Field(ge=0, le=13)
    grade: Literal["A", "B", "C", "D", "F"]
    role_fit: int = Field(ge=0, le=4)
    skills_alignment: int = Field(ge=0, le=4)
    seniority_fit: int = Field(ge=0, le=2)
    salary_signal: int = Field(ge=0, le=2)
    interview_likelihood: int = Field(ge=0, le=2)
    growth_trajectory: int = Field(ge=0, le=1)
    product_domain_fit: int = Field(ge=0, le=1)
    timeline: int = Field(ge=0, le=1)
    tier_bonus: int
    archetype: Literal[
        "distributed_systems",
        "identity_platform",
        "data_engineering",
        "ai_ml_engineer",
        "fintech_platform",
        "founding_engineer",
    ]
    reasoning: str = Field(min_length=10)


class PrioritizedEdit(BaseModel):
    priority: Literal["high", "medium", "low"]
    change: str
    rationale: str


class ReviewResult(BaseModel):
    verdict: Literal["Strong Fit", "Good Fit", "Moderate Fit", "Poor Fit"]
    overall_confidence: float = Field(ge=0.0, le=1.0)
    strengths: list[str]
    gaps: list[str]
    missing_keywords: list[str]
    strategic_angle: str
    prioritized_edits: list[PrioritizedEdit]


class NetworkingMessages(BaseModel):
    linkedin_dm: str = Field(min_length=10, max_length=800)
    cold_email: str = Field(min_length=50, max_length=2000)


class CoverLetter(BaseModel):
    text: str = Field(min_length=100)
    word_count: int = Field(ge=150, le=500)
    angle: str = Field(min_length=20)
    selected_proof_point_ids: list[str] = Field(min_length=2, max_length=5)
    company_research_signals: list[str] = Field(default_factory=list)


class CorpusBullet(BaseModel):
    role_id: str
    bullet_id: str
    title: str
    text: str = Field(min_length=20)


class CorpusRole(BaseModel):
    role_id: str
    company: str
    title: str
    dates: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    bullets: list[CorpusBullet]


class Corpus(BaseModel):
    name: str
    roles: list[CorpusRole]
    projects: list[CorpusBullet] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    other: dict[str, str] = Field(default_factory=dict)

    def get_bullet(self, bullet_id: str) -> CorpusBullet | None:
        """Find a bullet by ID across roles and projects."""
        for role in self.roles:
            for b in role.bullets:
                if b.bullet_id == bullet_id:
                    return b
        for p in self.projects:
            if p.bullet_id == bullet_id:
                return p
        return None

    def get_role(self, role_id: str) -> CorpusRole | None:
        for role in self.roles:
            if role.role_id == role_id:
                return role
        return None

    def find_role_by_company(self, company: str) -> CorpusRole | None:
        """Case-insensitive company name match for joining with resume."""
        for role in self.roles:
            if role.company.lower() == company.lower():
                return role
        return None

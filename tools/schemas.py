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
    word_count: int = Field(ge=100, le=600)

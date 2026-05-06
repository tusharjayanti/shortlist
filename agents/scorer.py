import json

from pydantic import ValidationError

from tools.config_loader import Config
from tools.llm import get_active_llm
from tools.prompts import load_prompt
from tools.schemas import JobScore
from tracker.audit import audited
from tracker.tracker import JobTracker

GRADES = [(11, "A"), (9, "B"), (7, "C"), (5, "D"), (0, "F")]

USER_TEMPLATE = """
Evaluate this job:

Company: {company}
Role: {title}
Location: {location}
URL: {url}

Job description:
{description}
"""


def _extract_json(text: str) -> str:
    """Remove markdown code fences that some LLMs add despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = text[text.index("\n") + 1:]
        if "```" in text:
            text = text[: text.rindex("```")]
    return text.strip()


class ScorerAgent:
    def __init__(self, tracker: JobTracker, config: Config):
        self.tracker = tracker
        self.config = config
        self.llm = get_active_llm()
        self._system_prompt_template = load_prompt("scorer")

    def _build_system_prompt(self) -> str:
        c = self.config.candidate
        return self._system_prompt_template.format(
            name=c.name,
            experience_years=c.experience_years,
            location=c.location.primary,
            roles=", ".join(c.roles),
            min_salary_lpa=c.min_salary_lpa,
            max_salary_lpa=c.max_salary_lpa,
            backend=", ".join(c.backend),
            databases=", ".join(c.databases),
            cloud_devops=", ".join(c.cloud_devops),
            data=", ".join(c.data),
            ai_tools=", ".join(c.ai_tools),
            strengths=", ".join(c.strengths),
        )

    def _calculate_grade(self, total: int) -> str:
        for threshold, grade in GRADES:
            if total >= threshold:
                return grade
        return "F"

    def _build_job_score(self, parsed: dict, tier_bonus: int) -> JobScore:
        role_fit = parsed["role_fit"]
        skills_alignment = parsed["skills_alignment"]

        base_total = (
            role_fit
            + skills_alignment
            + parsed["seniority_fit"]
            + parsed["salary_signal"]
            + parsed["interview_likelihood"]
            + parsed["growth_trajectory"]
            + parsed["product_domain_fit"]
            + parsed["timeline"]
        )

        if role_fit < 2 or skills_alignment < 2:
            base_total = min(base_total, 5)

        total = base_total + tier_bonus
        grade = self._calculate_grade(total)

        return JobScore(
            score=max(0, min(13, total)),
            grade=grade,
            role_fit=role_fit,
            skills_alignment=skills_alignment,
            seniority_fit=parsed["seniority_fit"],
            salary_signal=parsed["salary_signal"],
            interview_likelihood=parsed["interview_likelihood"],
            growth_trajectory=parsed["growth_trajectory"],
            product_domain_fit=parsed["product_domain_fit"],
            timeline=parsed["timeline"],
            tier_bonus=tier_bonus,
            archetype=parsed["archetype"],
            reasoning=parsed["reasoning"],
        )

    @audited(agent_name="scorer", action="score_job")
    def run(self, app_id: str, job: dict) -> JobScore:
        """
        Score a job across 8 dimensions, apply tier bonus,
        detect archetype, return validated JobScore.

        job dict keys: title, company, description, location, url.
        """
        system = self._build_system_prompt()
        tier_bonus = self.config.get_tier_bonus(job["company"])

        user = USER_TEMPLATE.format(
            company=job["company"],
            title=job["title"],
            location=job.get("location", "not specified"),
            url=job.get("url", "not specified"),
            description=job["description"],
        )

        last_error = None
        for attempt in range(3):
            response = self.llm.complete(
                messages=[{"role": "user", "content": user}],
                system_prompt=system,
                max_tokens=self.config.llm.max_tokens,
                temperature=self.config.llm.temperature,
            )
            self._last_llm_response = response

            try:
                parsed = json.loads(_extract_json(response.text))
                return self._build_job_score(parsed, tier_bonus)
            except (json.JSONDecodeError, ValidationError, KeyError) as e:
                last_error = e
                user = (
                    USER_TEMPLATE.format(
                        company=job["company"],
                        title=job["title"],
                        location=job.get("location", "not specified"),
                        url=job.get("url", "not specified"),
                        description=job["description"],
                    )
                    + f"\n\nPrevious attempt failed validation: {e}. "
                    + "Return ONLY valid JSON matching the exact schema."
                )

        raise RuntimeError(
            f"Scorer failed after 3 retries. Last error: {last_error}"
        )

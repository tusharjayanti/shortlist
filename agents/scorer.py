import json

from pydantic import ValidationError

from tools.config_loader import Config
from tools.llm import get_active_llm
from tools.schemas import JobScore
from tracker.audit import audited
from tracker.tracker import JobTracker

GRADES = [(11, "A"), (9, "B"), (7, "C"), (5, "D"), (0, "F")]

SYSTEM_PROMPT = """
You are an expert technical recruiter evaluating a senior \
engineering job for a specific candidate.

Candidate profile:
- Name: {name}
- {experience_years} years of senior backend + platform engineering
- Location: {location}
- Target roles: {roles}
- Salary range: ₹{min_salary_lpa}-{max_salary_lpa} LPA
- Backend stack: {backend}
- Databases: {databases}
- Cloud/DevOps: {cloud_devops}
- Data: {data}
- AI tools: {ai_tools}
- Key strengths: {strengths}

Score the job across 8 dimensions. Be honest — the candidate \
would rather skip a mediocre role than apply to one that is \
not a fit.

GATE-PASS DIMENSIONS (if either is below 2, total cannot \
exceed 5 regardless of other scores):

role_fit (0-4): Is this a senior IC engineering role the \
candidate wants?
  0 = completely wrong role type (sales engineer, manager-only)
  1 = weak fit (frontend heavy when candidate is backend)
  2 = partial fit (adjacent domain, transferable)
  3 = strong fit
  4 = perfect role type match

skills_alignment (0-4): Does the tech stack overlap with \
candidate's experience?
  0 = completely different stack
  1 = some overlap but major gaps
  2 = moderate overlap
  3 = strong overlap with 1-2 learnable gaps
  4 = near-perfect match

OTHER DIMENSIONS:

seniority_fit (0-2): Is the level appropriate for 7 years?
  0 = mismatched (junior or principal)
  1 = stretch (one level off — mid or staff)
  2 = target (senior)

salary_signal (0-2): Evidence of compensation in target range?
  0 = red flag (stated below ₹30 LPA, or ESOP-only startup)
  1 = ambiguous (no salary mentioned)
  2 = clear fit (stated range overlaps target)

interview_likelihood (0-2): Will this company likely interview \
this candidate?
  0 = unlikely (wants 10+ years, very specialised, or rigid requirements)
  1 = possible (reasonable fit on paper)
  2 = likely (clear match with senior engineers from similar backgrounds)

growth_trajectory (0-1): Is there a visible career path?
  0 = flat structure or unclear growth
  1 = clear IC ladder or explicit growth mentions

product_domain_fit (0-1): Does the problem domain resonate?
  0 = unrelated domain (adtech, gaming) when candidate targets infra
  1 = domain candidate has stated interest in

timeline (0-1): Is this an urgent hire vs slow burn?
  0 = slow/unclear timeline
  1 = urgent role (explicit fast hiring, backfill)

ARCHETYPE DETECTION:

Choose the archetype that best matches THIS role's needs:

- distributed_systems: p99 latency, microservices, scale, gRPC, Kafka
- identity_platform: auth, OAuth, OIDC, identity migration, security
- data_engineering: pipelines, Airflow, batch processing, data infra
- ai_ml_engineer: LLM integration, agents, AI-assisted development
- fintech_platform: payments, high-throughput transactions, compliance
- founding_engineer: 0 to 1, greenfield, small team, ambiguity

Return ONLY valid JSON with these exact keys:
{{
  "role_fit": <int 0-4>,
  "skills_alignment": <int 0-4>,
  "seniority_fit": <int 0-2>,
  "salary_signal": <int 0-2>,
  "interview_likelihood": <int 0-2>,
  "growth_trajectory": <int 0-1>,
  "product_domain_fit": <int 0-1>,
  "timeline": <int 0-1>,
  "archetype": "<one of the 6 archetypes>",
  "reasoning": "<2-3 sentences explaining key scores and archetype choice>"
}}

No markdown, no commentary outside the JSON. No explanation \
of the schema. Just the JSON object.
"""

USER_TEMPLATE = """
Evaluate this job:

Company: {company}
Role: {title}
Location: {location}
URL: {url}

Job description:
{description}
"""


def _strip_fences(text: str) -> str:
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

    def _build_system_prompt(self) -> str:
        c = self.config.candidate
        return SYSTEM_PROMPT.format(
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
                parsed = json.loads(_strip_fences(response.text))
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

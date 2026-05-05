import json

from pydantic import ValidationError

from agents.scorer import _strip_fences
from tools.config_loader import Config
from tools.llm import get_active_llm
from tools.schemas import ReviewResult
from tracker.audit import audited
from tracker.tracker import JobTracker

SYSTEM_PROMPT = """
You are a senior technical recruiter and resume strategist.
You have deep expertise in how ATS systems parse resumes and
how hiring managers evaluate senior engineering candidates
in the first 6 seconds of reading.

Candidate profile:
- Name: {name}
- {experience_years} years senior backend + platform engineering
- Stack: {backend}, {databases}, {cloud_devops}
- Strengths: {strengths}
- Target archetypes: {archetypes}

Analyse the candidate's resume against the job description
across three lenses:

LENS 1 — ATS SCAN
Which keywords from the JD are missing from the resume?
Focus only on technical terms, tools, and methodologies
that an ATS would match literally. Ignore soft skills.

LENS 2 — 6-SECOND HUMAN SCREEN
Would a senior engineering hiring manager understand this
candidate's value proposition in 6 seconds?
- Is the summary strong and role-specific?
- Do the top 2-3 bullets in each role show impact at scale?
- Is seniority clear from the language and metrics used?

LENS 3 — STRATEGIC FIT
Given the archetype detected for this role:
- What is the strongest narrative angle?
- Which of the candidate's experiences should lead?
- What should be de-emphasised for this specific role?
- Is this a step up, lateral move, or pivot?

Return ONLY valid JSON matching this schema exactly:
{{
  "verdict": "<one of: Strong Fit, Good Fit, Moderate Fit, Poor Fit>",
  "overall_confidence": <float 0.0 to 1.0>,
  "strengths": ["<strength 1>", "<strength 2>", ...],
  "gaps": ["<gap 1>", "<gap 2>", ...],
  "missing_keywords": ["<keyword 1>", "<keyword 2>", ...],
  "strategic_angle": "<2-3 sentences on strongest narrative>",
  "prioritized_edits": [
    {{
      "priority": "<high|medium|low>",
      "change": "<what to change>",
      "rationale": "<why this matters for this role>"
    }}
  ]
}}

No markdown. No commentary. Just the JSON object.
Include at least 1 high priority edit and no more than 7 edits total.
Order edits high → medium → low.
"""

USER_TEMPLATE = """
Job to evaluate:

Company: {company}
Role: {title}
Archetype detected: {archetype}
Location: {location}

Job description:
{description}

---

Candidate's current resume:
{resume_text}
"""


class ReviewerAgent:
    def __init__(self, tracker: JobTracker, config: Config):
        self.tracker = tracker
        self.config = config
        self.llm = get_active_llm()
        self._last_llm_response = None

    def _build_system_prompt(self) -> str:
        c = self.config.candidate
        archetype_names = list(self.config.archetypes.keys())
        return SYSTEM_PROMPT.format(
            name=c.name,
            experience_years=c.experience_years,
            backend=", ".join(c.backend),
            databases=", ".join(c.databases),
            cloud_devops=", ".join(c.cloud_devops),
            strengths=", ".join(c.strengths),
            archetypes=", ".join(archetype_names),
        )

    @audited(agent_name="reviewer", action="analyze_fit")
    def run(
        self,
        app_id: str,
        job: dict,
        archetype: str,
        resume_text: str,
    ) -> ReviewResult:
        """
        Analyse resume vs JD across three lenses.
        Returns ReviewResult with gaps, missing keywords,
        strategic angle, and prioritised edits.
        """
        system = self._build_system_prompt()
        user = USER_TEMPLATE.format(
            company=job["company"],
            title=job["title"],
            archetype=archetype,
            location=job.get("location", "not specified"),
            description=job["description"],
            resume_text=resume_text,
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
                return ReviewResult(**parsed)
            except (json.JSONDecodeError, ValidationError, KeyError) as e:
                last_error = e
                user = (
                    USER_TEMPLATE.format(
                        company=job["company"],
                        title=job["title"],
                        archetype=archetype,
                        location=job.get("location", "not specified"),
                        description=job["description"],
                        resume_text=resume_text,
                    )
                    + f"\n\nPrevious attempt failed: {e}. "
                    + "Return ONLY valid JSON matching the schema."
                )

        raise RuntimeError(
            f"Reviewer failed after 3 retries. Last error: {last_error}"
        )

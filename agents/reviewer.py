import json

from pydantic import ValidationError

from agents.scorer import _extract_json
from tools.config_loader import Config
from tools.llm import get_active_llm
from tools.prompts import load_prompt
from tools.schemas import ReviewResult
from tracker.audit import audited
from tracker.tracker import JobTracker

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
        self._system_prompt_template = load_prompt("reviewer")

    def _build_system_prompt(self) -> str:
        c = self.config.candidate
        archetype_names = list(self.config.archetypes.keys())
        return self._system_prompt_template.format(
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
                parsed = json.loads(_extract_json(response.text))
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

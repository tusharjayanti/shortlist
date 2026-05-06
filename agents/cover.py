import json

from pydantic import ValidationError

from agents.scorer import _extract_json
from tools.config_loader import Config
from tools.corpus import parse_corpus
from tools.llm import get_active_llm
from tools.prompts import load_prompt
from tools.schemas import Corpus, CoverLetter
from tracker.audit import audited
from tracker.tracker import JobTracker

USER_TEMPLATE = """
TARGET JOB:

Company: {company}
Role: {title}
Location: {location}

Job description:
{description}

---

CAREER CORPUS — select proof points from these bullets:

{corpus_text}

---

Write the cover letter for this role. Use the {archetype}
archetype framing. Surface your strategy in the angle field.
Every fact in the letter must trace to a bullet you select
from the corpus.
"""


class CoverLetterAgent:
    def __init__(self, tracker: JobTracker, config: Config):
        self.tracker = tracker
        self.config = config
        self.llm = get_active_llm()
        self._system_prompt_template = load_prompt("cover")
        self._last_llm_response = None

    def _build_system_prompt(self, archetype: str) -> str:
        c = self.config.candidate
        arch_config = self.config.archetypes.get(archetype)
        return self._system_prompt_template.format(
            name=c.name,
            experience_years=c.experience_years,
            target_role_description=", ".join(c.roles),
            archetype=archetype,
            archetype_lead=arch_config.lead_with if arch_config else "",
            archetype_proof_points=", ".join(
                arch_config.proof_points if arch_config else []
            ),
        )

    def _format_corpus_for_prompt(self, corpus: Corpus) -> str:
        """Serialize corpus with bullet IDs visible to LLM."""
        lines = []

        for role in corpus.roles:
            lines.append(f"## {role.company} ({role.title})")
            for bullet in role.bullets:
                lines.append(f"### [id: {bullet.bullet_id}] {bullet.title}")
                lines.append(bullet.text)
                lines.append("")

        if corpus.projects:
            lines.append("## Personal Projects")
            for proj in corpus.projects:
                lines.append(f"### [id: {proj.bullet_id}] {proj.title}")
                lines.append(proj.text)
                lines.append("")

        return "\n".join(lines)

    @audited(agent_name="cover_letter", action="write_letter")
    def run(
        self,
        app_id: str,
        job: dict,
        archetype: str,
        corpus_path: str = "experience.md",
        feedback: str | None = None,
    ) -> CoverLetter:
        """
        Generate a cover letter using corpus-grounded proof points.

        Returns CoverLetter with text, angle, selected_proof_point_ids,
        company_research_signals, and word_count.
        """
        corpus = parse_corpus(corpus_path)
        corpus_text = self._format_corpus_for_prompt(corpus)

        system = self._build_system_prompt(archetype)
        user = USER_TEMPLATE.format(
            company=job["company"],
            title=job["title"],
            location=job.get("location", "not specified"),
            description=job["description"],
            archetype=archetype,
            corpus_text=corpus_text,
        )

        if feedback:
            user += (
                f"\n\n---\n\n"
                f"USER FEEDBACK on previous version:\n{feedback}\n\n"
                f"Incorporate this feedback. You may select different "
                f"proof points if the feedback warrants a different "
                f"angle. Return the full JSON object."
            )

        last_error = None
        for attempt in range(3):
            response = self.llm.complete(
                messages=[{"role": "user", "content": user}],
                system_prompt=system,
                max_tokens=self.config.llm.max_tokens,
                temperature=0.4,
            )
            self._last_llm_response = response

            try:
                parsed = json.loads(_extract_json(response.text))

                actual_words = len(parsed["text"].split())
                parsed["word_count"] = actual_words

                if job["company"].lower() not in parsed["text"].lower():
                    raise ValueError(
                        f"Letter does not mention '{job['company']}'"
                    )

                invalid_ids = [
                    bid for bid in parsed.get("selected_proof_point_ids", [])
                    if corpus.get_bullet(bid) is None
                ]
                if invalid_ids:
                    raise ValueError(
                        f"Selected bullet IDs do not exist in corpus: "
                        f"{invalid_ids}"
                    )

                return CoverLetter(**parsed)

            except (json.JSONDecodeError, ValidationError,
                    KeyError, ValueError) as e:
                last_error = e
                user += (
                    f"\n\nPrevious attempt failed: {e}. "
                    f"Return ONLY valid JSON with all required fields. "
                    f"selected_proof_point_ids must be real bullet IDs "
                    f"from the corpus above."
                )

        raise RuntimeError(
            f"Cover letter agent failed after 3 retries. "
            f"Last error: {last_error}"
        )

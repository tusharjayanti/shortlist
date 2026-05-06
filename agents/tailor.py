from agents.scorer import _extract_json
from tools.config_loader import Config
from tools.llm import get_active_llm
from tools.prompts import load_prompt
from tools.resume import read_resume, write_tailored_resume
from tools.schemas import ReviewResult
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

REVIEWER'S ANALYSIS:
Verdict: {verdict}
Strategic angle: {strategic_angle}

Missing keywords to incorporate: {missing_keywords}

Prioritised edits:
{edits_text}

---

CURRENT RESUME (LaTeX):
{resume_tex}
"""


class TailorAgent:
    def __init__(self, tracker: JobTracker, config: Config):
        self.tracker = tracker
        self.config = config
        self.llm = get_active_llm()
        self._last_llm_response = None
        self._system_prompt_template = load_prompt("tailor")

    def _build_system_prompt(self, archetype: str) -> str:
        c = self.config.candidate
        arch_config = self.config.archetypes.get(archetype)
        return self._system_prompt_template.format(
            name=c.name,
            experience_years=c.experience_years,
            archetype=archetype,
            archetype_lead=arch_config.lead_with if arch_config else "",
            archetype_proof_points=", ".join(
                arch_config.proof_points if arch_config else []
            ),
        )

    def _format_edits(self, review: ReviewResult) -> str:
        lines = []
        for edit in review.prioritized_edits:
            lines.append(
                f"[{edit.priority.upper()}] {edit.change}\n"
                f"  Rationale: {edit.rationale}"
            )
        return "\n\n".join(lines)

    @audited(agent_name="tailor", action="tailor_resume")
    def run(
        self,
        app_id: str,
        job: dict,
        archetype: str,
        review: ReviewResult,
        resume_tex: str | None = None,
        feedback: str | None = None,
    ) -> dict:
        """
        Tailor the resume for a specific job using archetype
        framing and reviewer's analysis.

        If resume_tex is None, reads from resume/resume.tex.
        If feedback is provided, it's from the ReviewCoordinator —
        the user rejected the previous version and gave notes.

        Returns dict with:
          tex_content: str  — the full tailored LaTeX
          tex_path: str     — where it was saved
          version: int      — version number in resume_versions
          changes_summary: str — what was changed
        """
        if resume_tex is None:
            resume_tex = read_resume()

        system = self._build_system_prompt(archetype)

        edits_text = self._format_edits(review)
        missing_kw = ", ".join(review.missing_keywords)

        user = USER_TEMPLATE.format(
            company=job["company"],
            title=job["title"],
            location=job.get("location", "not specified"),
            description=job["description"],
            verdict=review.verdict,
            strategic_angle=review.strategic_angle,
            missing_keywords=missing_kw,
            edits_text=edits_text,
            resume_tex=resume_tex,
        )

        if feedback:
            user += (
                f"\n\n---\n\n"
                f"USER FEEDBACK on previous version:\n{feedback}\n\n"
                f"Incorporate this feedback while keeping all other "
                f"improvements. Return the full LaTeX document."
            )

        response = self.llm.complete(
            messages=[{"role": "user", "content": user}],
            system_prompt=system,
            max_tokens=8192,
            temperature=0.2,
        )
        self._last_llm_response = response

        tailored_tex = response.text.strip()

        if tailored_tex.startswith("```"):
            lines = tailored_tex.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            tailored_tex = "\n".join(lines)

        if not tailored_tex.strip().startswith("\\documentclass"):
            raise RuntimeError(
                "Tailor output doesn't start with \\documentclass. "
                "LLM may have returned commentary instead of LaTeX."
            )

        candidate_name = self.config.candidate.name.replace(" ", "_")
        company_slug = job["company"].replace(" ", "_").replace("-", "_")
        role_slug = job["title"].replace(" ", "_").replace("-", "_")[:50]
        output_path = f"output/{candidate_name}_{company_slug}_{role_slug}.tex"

        written_path = write_tailored_resume(
            original_tex=resume_tex,
            tailored_tex=tailored_tex,
            output_path=output_path,
        )

        version = self.tracker.save_resume_version(
            app_id=app_id,
            tex_path=written_path,
            pdf_path=None,
            changes_summary=f"Archetype: {archetype}. "
                + f"Edits applied: {len(review.prioritized_edits)}. "
                + (f"User feedback: {feedback[:100]}" if feedback else "Initial version."),
            feedback_given=feedback,
        )

        return {
            "tex_content": tailored_tex,
            "tex_path": written_path,
            "version": version,
            "changes_summary": f"v{version}: {archetype} framing, "
                + f"{len(review.missing_keywords)} keywords added, "
                + f"{len(review.prioritized_edits)} edits applied",
        }

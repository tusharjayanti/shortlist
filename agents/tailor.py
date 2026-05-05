from agents.scorer import _extract_json
from tools.config_loader import Config
from tools.llm import get_active_llm
from tools.resume import read_resume, write_tailored_resume
from tools.schemas import ReviewResult
from tracker.audit import audited
from tracker.tracker import JobTracker

SYSTEM_PROMPT = """
You are an expert resume writer specialising in senior
engineering roles. You tailor resumes by rewriting specific
sections to match a target job description, guided by a
gap analysis and an archetype framing.

Candidate profile:
- Name: {name}
- {experience_years} years experience
- Primary archetype for this role: {archetype}
- Archetype lead: {archetype_lead}
- Archetype proof points: {archetype_proof_points}

You will receive:
1. The candidate's current LaTeX resume
2. A ReviewResult with gaps, missing keywords, strategic
   angle, and prioritised edits
3. The target job description

Your job is to produce a COMPLETE, VALID LaTeX resume that
incorporates the reviewer's edits while following the archetype
framing.

WHAT YOU MUST CHANGE (guided by ReviewResult):
- Summary/objective paragraph: rewrite to lead with the
  archetype's framing and address the strategic angle
- Skills section: reorder to put JD-relevant skills first
- Experience bullets: rewrite up to 3 bullets per role to
  incorporate missing keywords and address gaps
- Order of experience sections: if reviewer says to reorder,
  do so

WHAT YOU MUST NEVER DO:
- Never fabricate a company, role, project, or technology
- Never change any numbers or metrics (percentages, counts,
  durations) — these are facts
- Never add skills the candidate doesn't have
- Never remove the EDUCATION section
- Never make the resume longer than the original
- Never change the LaTeX document class, packages, or
  formatting commands
- Never add placeholder text like "XXX" or "[insert here]"
- Never remove entire job entries — only rewrite bullets
- Never change job titles, company names, or dates

FORMATTING RULES:
- Return the COMPLETE LaTeX document from \\documentclass to
  \\end{{document}}
- Preserve all LaTeX commands, environments, and structure
- Do not change the LaTeX document class, packages, geometry
  margins, or formatting commands
- Do not add LaTeX comments explaining your changes
- Match the verbosity and density of the original resume —
  bullets should be substantive but not padded
- 1-2 pages is acceptable for senior engineering resumes;
  prioritise content quality over page count

Return ONLY the complete LaTeX content. No markdown fencing,
no explanation, no commentary before or after. Just the raw
LaTeX starting with \\documentclass.
"""

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

    def _build_system_prompt(self, archetype: str) -> str:
        c = self.config.candidate
        arch_config = self.config.archetypes.get(archetype)
        return SYSTEM_PROMPT.format(
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

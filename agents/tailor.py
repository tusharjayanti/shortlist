import logging
import re

from agents.scorer import _extract_json  # noqa: F401  (kept for parity with reviewer/scorer)
from tools.config_loader import Config
from tools.corpus import parse_corpus
from tools.llm import get_active_llm
from tools.prompts import load_prompt
from tools.resume import read_resume, write_tailored_resume
from tools.schemas import Corpus, ReviewResult
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

CURRENT RESUME (LaTeX) — use as both template and content source:

{resume_tex}

---

EXPERIENCE CORPUS (Markdown) — additional bullets you may pull from:

{corpus_text}

---

Produce the tailored LaTeX resume. Every bullet must trace to
either the resume above or the corpus above. Use the resume's
LaTeX structure and formatting; pull richer bullets from the
corpus where the JD calls for content the resume currently lacks.
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
            target_role_description=", ".join(c.roles),
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

    def _format_corpus_for_prompt(self, corpus: Corpus) -> str:
        """Serialize corpus as Markdown for inclusion in LLM prompt."""
        lines = [f"# {corpus.name}", ""]

        for role in corpus.roles:
            lines.append(f"## {role.company} ({role.title})")
            if role.dates:
                lines.append(f"**Dates:** {role.dates}")
            if role.tech_stack:
                lines.append(f"**Tech stack:** {', '.join(role.tech_stack)}")
            lines.append("")

            for bullet in role.bullets:
                lines.append(f"### {bullet.title}")
                lines.append(bullet.text)
                lines.append("")

        if corpus.projects:
            lines.append("## Personal Projects")
            for proj in corpus.projects:
                lines.append(f"### {proj.title}")
                lines.append(proj.text)
                lines.append("")

        if corpus.education:
            lines.append("## Education")
            for edu in corpus.education:
                lines.append(edu)
            lines.append("")

        return "\n".join(lines)

    def _verify_no_obvious_fabrication(
        self,
        tailored_tex: str,
        resume_tex: str,
        corpus: Corpus,
    ) -> None:
        """
        Light fabrication check. Build a corpus of all known facts
        and verify that distinctive content in the output appears
        in at least one source.

        Intentionally permissive — catches obvious hallucinations
        (made-up companies, fake projects) but allows reasonable
        rewording.
        """
        all_known_text = (
            resume_tex + "\n" + self._format_corpus_for_prompt(corpus)
        ).lower()

        suspicious_tokens = []
        for match in re.finditer(r'\\textbf{([^}]+)}', tailored_tex):
            token = match.group(1).strip()
            if len(token) < 4 or token.lower() in [
                "education", "experience", "skills", "summary"
            ]:
                continue
            if token.lower() not in all_known_text:
                suspicious_tokens.append(token)

        if suspicious_tokens:
            logging.warning(
                f"Tailor output contains tokens not found in "
                f"resume.tex or experience.md: {suspicious_tokens[:5]}. "
                f"This may indicate fabrication. Review before sending."
            )

    def _verify_chronological_order(
        self,
        tailored_tex: str,
        corpus: Corpus,
    ) -> None:
        """
        Warn if the tailored resume's role order doesn't match
        reverse chronological order based on end dates from corpus.
        """
        from datetime import datetime

        def parse_end_date(dates_str: str) -> datetime:
            """
            Parse the end date from strings like
            'Nov 2023 – Sept 2025' or 'Sept 2020 – Sept 2022'.
            Returns datetime.max for 'Present' or unparseable.
            """
            if not dates_str:
                return datetime.min

            parts = re.split(r'\s*[–—-]\s*', dates_str.strip())
            if len(parts) < 2:
                return datetime.min

            end_part = parts[-1].strip().lower()
            if 'present' in end_part or 'current' in end_part:
                return datetime.max

            for fmt in ['%b %Y', '%B %Y', '%m/%Y', '%Y']:
                try:
                    return datetime.strptime(end_part, fmt)
                except ValueError:
                    continue
            return datetime.min

        roles_with_dates = [
            (role.company, parse_end_date(role.dates))
            for role in corpus.roles
        ]
        expected_order = sorted(
            roles_with_dates,
            key=lambda x: x[1],
            reverse=True,
        )
        expected_companies = [c for c, _ in expected_order]

        tex_companies_in_order = []
        for match in re.finditer(
            r'\\resumeSubheading\s*\{\\textbf\{([^}]+)\}\}',
            tailored_tex,
        ):
            tex_companies_in_order.append(match.group(1).strip())

        if not tex_companies_in_order:
            return

        tex_indices = []
        for tex_company in tex_companies_in_order:
            for i, exp_company in enumerate(expected_companies):
                if (tex_company.lower() == exp_company.lower()
                        or exp_company.lower() in tex_company.lower()
                        or tex_company.lower() in exp_company.lower()):
                    tex_indices.append(i)
                    break

        is_chronological = all(
            tex_indices[i] <= tex_indices[i + 1]
            for i in range(len(tex_indices) - 1)
        )

        if not is_chronological:
            logging.warning(
                f"Tailored resume role order is not reverse chronological. "
                f"Resume order: {tex_companies_in_order}. "
                f"Expected order (by end date): {expected_companies}. "
                f"Review before sending."
            )

    @audited(agent_name="tailor", action="tailor_resume")
    def run(
        self,
        app_id: str,
        job: dict,
        archetype: str,
        review: ReviewResult,
        resume_tex: str | None = None,
        corpus_path: str = "experience.md",
        feedback: str | None = None,
    ) -> dict:
        """
        Tailor the resume using both resume.tex and experience.md.

        The LLM may keep, reword, replace, add, or drop bullets,
        drawing from either source. Every bullet in the output
        must trace to one of the two sources.
        """
        if resume_tex is None:
            resume_tex = read_resume()

        corpus = parse_corpus(corpus_path)
        corpus_text = self._format_corpus_for_prompt(corpus)

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
            corpus_text=corpus_text,
        )

        if feedback:
            user += (
                f"\n\n---\n\n"
                f"USER FEEDBACK on previous version:\n{feedback}\n\n"
                f"Incorporate this feedback while keeping all "
                f"trace-to-source guarantees. Return the full LaTeX."
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
            lines = tailored_tex.split("\n")[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            tailored_tex = "\n".join(lines)

        if not tailored_tex.strip().startswith("\\documentclass"):
            raise RuntimeError(
                "Tailor output doesn't start with \\documentclass."
            )

        self._verify_no_obvious_fabrication(
            tailored_tex, resume_tex, corpus
        )

        self._verify_chronological_order(tailored_tex, corpus)

        candidate_name = self.config.candidate.name.replace(" ", "_")
        company_slug = job["company"].lower().replace(" ", "_").replace("-", "_")
        role_slug = job["title"].lower().replace(" ", "_").replace("-", "_")[:50]
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
            changes_summary=(
                f"Archetype: {archetype}. "
                f"Sources: resume.tex + experience.md. "
                f"Edits applied: {len(review.prioritized_edits)}. "
                + (f"User feedback: {feedback[:100]}" if feedback
                   else "Initial version.")
            ),
            feedback_given=feedback,
        )

        return {
            "tex_content": tailored_tex,
            "tex_path": written_path,
            "version": version,
            "changes_summary": (
                f"v{version}: {archetype} framing, "
                f"{len(review.missing_keywords)} keywords, "
                f"corpus-augmented"
            ),
        }

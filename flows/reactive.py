import logging
import webbrowser

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from agents.cover import CoverLetterAgent
from agents.networker import NetworkerAgent
from agents.reviewer import ReviewerAgent
from agents.scorer import ScorerAgent
from agents.tailor import TailorAgent
from coordinator.review import ReviewCoordinator
from tools.browser import open_job_page
from tools.compiler import compile_pdf
from tools.config_loader import Config
from tools.resume import read_resume
from tools.scraper import fetch_job
from tracker.tracker import JobTracker


class ReactiveFlow:
    """
    User pastes a URL or JD text. System scrapes (or accepts
    pasted text), scores, reviews, tailors, writes cover letter,
    generates outreach, then enters review coordinator. PDF
    compiles after all artifacts approved.
    """

    def __init__(self, tracker: JobTracker, config: Config):
        self.tracker = tracker
        self.config = config
        self.console = Console()
        self.scorer = ScorerAgent(tracker, config)
        self.reviewer = ReviewerAgent(tracker, config)
        self.tailor = TailorAgent(tracker, config)
        self.cover = CoverLetterAgent(tracker, config)
        self.networker = NetworkerAgent(tracker, config)
        self.coordinator = ReviewCoordinator(
            tracker, config,
            self.tailor, self.cover, self.networker,
        )

    def run(self, input_text: str) -> dict:
        """
        Main entry point. input_text is either a URL (http(s)://)
        or a pasted JD as plain text.

        Returns dict with status, app_id, and paths to artifacts.
        """
        self.console.print(Panel.fit(
            "[bold cyan]Reactive Flow[/bold cyan]",
            border_style="cyan",
        ))

        # Step 1 — Resolve input to job dict
        is_url = input_text.startswith(("http://", "https://"))

        if is_url:
            # Dedup before paying for scrape + user input
            if self.tracker.is_url_seen(input_text):
                self.console.print(
                    f"[yellow]Already seen: {input_text}[/yellow]"
                )
                return {"status": "duplicate", "url": input_text}

            job = self._scrape_url(input_text)
            if job is None:
                return {"status": "scrape_failed", "url": input_text}
            self.tracker.mark_url_seen(input_text)
        else:
            job = self._parse_pasted_jd(input_text)

        # Step 2 — Score
        self.console.print("\n[dim]Scoring...[/dim]")
        app_id = self.tracker.create_application(
            company=job["company"],
            role=job["title"],
            job_url=job.get("url", ""),
            tier=self.config.get_company_tier(job["company"]),
            score=0,
            grade="F",
            archetype="",
            source="reactive",
        )

        score_result = self.scorer.run(app_id, job)
        self._print_score_summary(job, score_result)

        # Below-threshold short-circuit
        # NOTE: spec used min_score_to_surface; existing config field is minimum_score.
        min_score = self.config.scoring.minimum_score
        if score_result.score < min_score:
            self.console.print(Panel(
                f"[yellow]Score {score_result.score} below "
                f"threshold {min_score}. Skipping pipeline.[/yellow]",
                border_style="yellow",
            ))
            self.tracker.update_application_status(app_id, status="scored")
            return {
                "status": "scored_below_threshold",
                "app_id": app_id,
                "score": score_result.score,
                "grade": score_result.grade,
            }

        # Step 3 — Confirm with user before spending more tokens
        proceed = Prompt.ask(
            "\n[bold]Proceed with full pipeline?[/bold] "
            "(reviewer + tailor + cover + networker)",
            choices=["y", "n"],
            default="y",
        )
        if proceed == "n":
            return {
                "status": "user_skipped",
                "app_id": app_id,
                "score": score_result.score,
                "grade": score_result.grade,
            }

        # Step 4 — Reviewer
        self.console.print("\n[dim]Running reviewer...[/dim]")
        resume_text = read_resume()
        review = self.reviewer.run(
            app_id, job, score_result.archetype, resume_text,
        )
        self.console.print(
            f"[dim]Reviewer verdict: {review.verdict} "
            f"(confidence {review.overall_confidence:.2f})[/dim]"
        )

        # Step 5 — Coordinator (handles tailor + cover + networker + iteration)
        result = self.coordinator.run(
            app_id, job, score_result.archetype, review,
        )

        if result["aborted"]:
            self.tracker.update_application_status(
                app_id, status="resume_tailored",
            )
            return {"status": "aborted", "app_id": app_id}

        # Step 6 — Compile PDF
        self.console.print("\n[dim]Compiling PDF...[/dim]")
        try:
            pdf_path = compile_pdf(result["resume_path"])
            self.console.print(f"[green]PDF: {pdf_path}[/green]")
        except Exception as e:
            self.console.print(f"[red]PDF compilation failed: {e}[/red]")
            pdf_path = None

        # Step 7 — Approve
        self.tracker.update_application_status(app_id, status="approved")

        # Step 8 — Open the PDF and the JD URL for final review
        if pdf_path:
            try:
                webbrowser.open(f"file://{pdf_path}")
            except Exception:
                pass

        if job.get("url"):
            try:
                open_job_page(job["url"], self.config)
            except Exception:
                pass

        return {
            "status": "completed",
            "app_id": app_id,
            "score": score_result.score,
            "grade": score_result.grade,
            "archetype": score_result.archetype,
            "resume_tex": result["resume_path"],
            "resume_pdf": pdf_path,
            "cover_letter": result["cover_letter"],
            "networking": result["networking"],
        }

    def _scrape_url(self, url: str) -> dict | None:
        """Scrape a URL into a job dict. Falls back to manual paste."""
        try:
            self.console.print(f"\n[dim]Scraping {url}...[/dim]")
            result = fetch_job(url, self.config)

            if result.get("blocked") or result.get("gated"):
                self.console.print(
                    "[yellow]Scrape blocked/gated. "
                    "Paste JD manually below:[/yellow]"
                )
                return self._prompt_for_pasted_jd(url=url)

            jd_text = result.get("description", "") or ""
            if len(jd_text) < 200:
                self.console.print(
                    "[yellow]Page returned minimal content. "
                    "Paste JD manually below:[/yellow]"
                )
                return self._prompt_for_pasted_jd(url=url)

            return self._parse_pasted_jd(
                jd_text, url=url, title_default=result.get("title", ""),
            )
        except Exception as e:
            self.console.print(f"[red]Scrape failed: {e}[/red]")
            self.console.print("[yellow]Paste JD manually below:[/yellow]")
            return self._prompt_for_pasted_jd(url=url)

    def _prompt_for_pasted_jd(self, url: str = "") -> dict | None:
        """Interactive: user pastes JD text."""
        self.console.print(
            "[dim]Paste the job description. "
            "Type 'END' on a blank line when done:[/dim]"
        )
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == "END":
                break
            lines.append(line)

        jd_text = "\n".join(lines)
        if not jd_text.strip():
            return None
        return self._parse_pasted_jd(jd_text, url=url)

    def _parse_pasted_jd(
        self, text: str, url: str = "", title_default: str = "",
    ) -> dict:
        """
        Extract company and title from pasted JD text.
        First non-empty line is the title default; company always
        prompted.
        """
        if not title_default:
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            title_default = lines[0][:120] if lines else "Unknown Role"

        title = Prompt.ask("[bold]Role title[/bold]", default=title_default)
        company = Prompt.ask("[bold]Company name[/bold]")
        location = Prompt.ask(
            "[bold]Location[/bold]", default="not specified",
        )

        return {
            "title": title,
            "company": company,
            "location": location,
            "description": text,
            "url": url,
        }

    def _print_score_summary(self, job: dict, score_result) -> None:
        table = Table(title=f"{job['company']} — {job['title']}")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="white")
        table.add_row("Score", f"{score_result.score}/13")
        table.add_row("Grade", score_result.grade)
        table.add_row("Archetype", score_result.archetype)
        table.add_row("Tier bonus", str(score_result.tier_bonus))
        self.console.print(table)

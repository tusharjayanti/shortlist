import logging

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from agents.finder import FinderAgent
from agents.scorer import ScorerAgent
from flows.reactive import ReactiveFlow
from tools.config_loader import Config
from tracker.tracker import JobTracker


class ProactiveFlow:
    """
    Discover → score → shortlist table → user picks →
    delegate each pick to ReactiveFlow.
    """

    def __init__(self, tracker: JobTracker, config: Config):
        self.tracker = tracker
        self.config = config
        self.console = Console()
        self.scorer = ScorerAgent(tracker, config)
        self.reactive = ReactiveFlow(tracker, config)

    def run(self) -> dict:
        """Discover, score, shortlist, hand picks to ReactiveFlow."""
        self.console.print(Panel.fit(
            "[bold cyan]Proactive Flow[/bold cyan]",
            border_style="cyan",
        ))

        # Step 1 — Discover
        self.console.print("\n[dim]Running finder...[/dim]")
        finder = FinderAgent(self.tracker, self.config)
        jobs = finder.run()

        if not jobs:
            self.console.print("[yellow]No new jobs discovered.[/yellow]")
            return {"status": "no_jobs", "jobs_scored": 0}

        self.console.print(
            f"[green]Found {len(jobs)} new jobs. Scoring...[/green]"
        )

        # Step 2 — Score all
        scored = []
        for job in jobs:
            try:
                app_id = self.tracker.create_application(
                    company=job["company"],
                    role=job["title"],
                    job_url=job.get("url", ""),
                    tier=self.config.get_company_tier(job["company"]),
                    score=0,
                    grade="F",
                    archetype="",
                    source="proactive",
                )
                score_result = self.scorer.run(app_id, job)
                scored.append({
                    "app_id": app_id,
                    "job": job,
                    "score": score_result,
                })
            except Exception as e:
                logging.warning(
                    f"Scoring failed for {job.get('title', '?')} "
                    f"at {job.get('company', '?')}: {e}"
                )
                continue

        # Step 3 — Filter to shortlist
        # NOTE: spec used min_score_to_surface; existing config field is minimum_score.
        min_score = self.config.scoring.minimum_score
        shortlist = [s for s in scored if s["score"].score >= min_score]
        shortlist.sort(key=lambda s: s["score"].score, reverse=True)

        if not shortlist:
            self.console.print(Panel(
                f"[yellow]No jobs above threshold "
                f"({min_score}). Scored {len(scored)} jobs.[/yellow]",
                border_style="yellow",
            ))
            return {
                "status": "no_shortlist",
                "jobs_scored": len(scored),
                "shortlist_size": 0,
            }

        # Step 4 — Show shortlist table
        self._print_shortlist_table(shortlist)

        # Step 5 — User picks
        self.console.print(
            "\n[bold]Which jobs to process? "
            "(comma-separated indices, or 'all', or 'none')[/bold]"
        )
        picks_str = Prompt.ask("Picks", default="none")

        if picks_str.lower() == "none":
            return {
                "status": "user_skipped",
                "jobs_scored": len(scored),
                "shortlist_size": len(shortlist),
            }

        if picks_str.lower() == "all":
            picks = list(range(len(shortlist)))
        else:
            try:
                picks = [
                    int(x.strip()) for x in picks_str.split(",")
                    if x.strip()
                ]
            except ValueError:
                self.console.print("[red]Invalid input.[/red]")
                return {"status": "invalid_input"}

        # Step 6 — Delegate each pick to ReactiveFlow
        completed = 0
        aborted = 0
        for idx in picks:
            if idx < 0 or idx >= len(shortlist):
                continue
            picked = shortlist[idx]
            self.console.rule(
                f"[bold]Processing pick {idx + 1}: "
                f"{picked['job']['company']}[/bold]"
            )
            try:
                if picked["job"].get("url"):
                    result = self.reactive.run(picked["job"]["url"])
                else:
                    result = self.reactive.run(
                        picked["job"].get("description", "")
                    )

                if result.get("status") == "completed":
                    completed += 1
                elif result.get("status") == "aborted":
                    aborted += 1
            except Exception as e:
                logging.error(f"Pipeline failed for pick {idx}: {e}")
                continue

        return {
            "status": "ok",
            "jobs_scored": len(scored),
            "shortlist_size": len(shortlist),
            "completed": completed,
            "aborted": aborted,
        }

    def _print_shortlist_table(self, shortlist: list) -> None:
        table = Table(title="Shortlist (above threshold)")
        table.add_column("#", style="dim")
        table.add_column("Company", style="cyan")
        table.add_column("Role", style="white")
        table.add_column("Score", justify="right")
        table.add_column("Grade", justify="center")
        table.add_column("Archetype", style="magenta")
        table.add_column("Tier", justify="center")

        for i, s in enumerate(shortlist):
            grade_color = {
                "A": "green", "B": "blue",
                "C": "yellow", "D": "red", "F": "red",
            }.get(s["score"].grade, "white")
            table.add_row(
                str(i),
                s["job"]["company"][:30],
                s["job"]["title"][:40],
                f"{s['score'].score}/13",
                f"[{grade_color}]{s['score'].grade}[/{grade_color}]",
                s["score"].archetype,
                str(self.config.get_company_tier(s["job"]["company"])),
            )
        self.console.print(table)

import logging
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from flows.audit import AuditFlow
from flows.pipeline import PipelineFlow
from flows.proactive import ProactiveFlow
from flows.reactive import ReactiveFlow
from flows.status import StatusFlow
from tools.config_loader import load_config
from tools.llm import init_llm
from tracker.tracker import JobTracker


class Shortlist:
    """
    Menu-driven entry point for the Shortlist system.

    Wraps the five flows with a top-level menu. Handles:
      - Initial config and LLM provider setup
      - Menu loop until user exits
      - Graceful Ctrl+C handling that doesn't lose work
      - Clear error messages when things go wrong
    """

    def __init__(self):
        self.console = Console()
        self.config = None
        self.tracker = None

    def bootstrap(self) -> bool:
        """
        Load config, init LLM, connect to tracker.
        Returns True if successful, False otherwise.
        """
        try:
            self.console.print("[dim]Loading config...[/dim]")
            self.config = load_config()
        except FileNotFoundError as e:
            self.console.print(Panel(
                f"[red]Config not found: {e}[/red]\n\n"
                "Copy config.example.yaml to config.yaml and "
                "fill in your details.",
                border_style="red",
            ))
            return False
        except Exception as e:
            self.console.print(f"[red]Config load failed: {e}[/red]")
            return False

        try:
            init_llm(self.config)
        except Exception as e:
            self.console.print(Panel(
                f"[red]LLM init failed: {e}[/red]\n\n"
                "Check your .env file has the right API keys.",
                border_style="red",
            ))
            return False

        try:
            self.tracker = JobTracker()
        except Exception as e:
            self.console.print(Panel(
                f"[red]Database connection failed: {e}[/red]\n\n"
                "Run: docker compose up -d",
                border_style="red",
            ))
            return False

        return True

    def show_banner(self) -> None:
        """Print the welcome banner."""
        self.console.print(Panel.fit(
            "[bold cyan]Shortlist[/bold cyan]\n"
            "[dim]AI-powered job search copilot[/dim]\n\n"
            f"Candidate: [bold]{self.config.candidate.name}[/bold]\n"
            f"Targeting: {self.config.candidate.location.primary} "
            f"({self.config.candidate.experience_years}+ years)\n"
            f"LLM provider: [bold]{self.config.llm.provider}[/bold]",
            border_style="cyan",
        ))

    def show_menu(self) -> str:
        """Print the menu and return the user's choice."""
        menu_table = Table.grid(padding=(0, 2))
        menu_table.add_column(style="bold cyan", justify="right")
        menu_table.add_column(style="white")
        menu_table.add_row("1.", "Evaluate a specific job (paste URL or JD)")
        menu_table.add_row("2.", "Run finder + score new jobs (proactive)")
        menu_table.add_row("3.", "Resume an in-progress application")
        menu_table.add_row("4.", "View pipeline status")
        menu_table.add_row("5.", "View audit log for an application")
        menu_table.add_row("6.", "View grade distribution")
        menu_table.add_row("7.", "View token usage and cost")
        menu_table.add_row("q.", "Quit")

        self.console.print()
        self.console.print(Panel(menu_table, title="Menu", border_style="dim"))

        choice = Prompt.ask(
            "\n[bold]Choose[/bold]",
            choices=["1", "2", "3", "4", "5", "6", "7", "q"],
            default="1",
        )
        return choice

    def run_menu_choice(self, choice: str) -> bool:
        """
        Execute the chosen menu action.
        Returns False if user wants to quit, True to continue.
        """
        if choice == "q":
            return False

        try:
            if choice == "1":
                self._evaluate_job()
            elif choice == "2":
                self._proactive_scan()
            elif choice == "3":
                self._resume_application()
            elif choice == "4":
                self._show_status()
            elif choice == "5":
                self._show_audit()
            elif choice == "6":
                self._show_grades()
            elif choice == "7":
                self._show_costs()
        except KeyboardInterrupt:
            self.console.print(
                "\n[yellow]Interrupted. Returning to menu.[/yellow]"
            )
        except Exception as e:
            self.console.print(Panel(
                f"[red]Action failed: {e}[/red]",
                border_style="red",
            ))
            logging.exception("Menu action failed")

        return True

    def _evaluate_job(self) -> None:
        """Menu option 1: reactive flow on URL or JD text."""
        self.console.print(
            "\n[bold]Paste a job URL or job description[/bold]"
        )
        self.console.print(
            "[dim](URL must start with http:// or https://. "
            "For JD text, end with 'END' on a blank line)[/dim]"
        )

        first_line = Prompt.ask("Input")

        if first_line.startswith(("http://", "https://")):
            input_text = first_line
        else:
            lines = [first_line]
            self.console.print(
                "[dim]Continuing paste mode. "
                "Type 'END' on a blank line when done:[/dim]"
            )
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line.strip() == "END":
                    break
                lines.append(line)
            input_text = "\n".join(lines)

        if not input_text.strip():
            self.console.print(
                "[yellow]Empty input. Returning to menu.[/yellow]"
            )
            return

        flow = ReactiveFlow(self.tracker, self.config)
        result = flow.run(input_text)

        self._summarize_reactive_result(result)

    def _proactive_scan(self) -> None:
        """Menu option 2: proactive flow."""
        flow = ProactiveFlow(self.tracker, self.config)
        result = flow.run()

        self.console.print(Panel(
            f"[bold]Scan complete[/bold]\n\n"
            f"Jobs scored: {result.get('jobs_scored', 0)}\n"
            f"Shortlist size: {result.get('shortlist_size', 0)}\n"
            f"Completed: {result.get('completed', 0)}\n"
            f"Aborted: {result.get('aborted', 0)}",
            border_style="green",
        ))

    def _resume_application(self) -> None:
        """Menu option 3: pipeline flow."""
        flow = PipelineFlow(self.tracker, self.config)
        resumable = flow.list_resumable()

        if not resumable:
            self.console.print(
                "[yellow]No resumable applications.[/yellow]"
            )
            return

        table = Table(title="Resumable applications")
        table.add_column("#", style="dim")
        table.add_column("Company", style="cyan")
        table.add_column("Role")
        table.add_column("Score", justify="right")
        table.add_column("Grade", justify="center")
        table.add_column("Status", style="yellow")

        for i, app in enumerate(resumable):
            table.add_row(
                str(i),
                app.get("company", "")[:25],
                app.get("role", "")[:35],
                str(app.get("score", "")),
                app.get("grade", ""),
                app.get("status", ""),
            )
        self.console.print(table)

        choice = Prompt.ask(
            "\n[bold]Pick an application to resume[/bold] "
            "(index or 'cancel')",
            default="cancel",
        )
        if choice == "cancel":
            return

        try:
            idx = int(choice)
            if idx < 0 or idx >= len(resumable):
                self.console.print("[red]Invalid index.[/red]")
                return
        except ValueError:
            self.console.print("[red]Invalid input.[/red]")
            return

        app = resumable[idx]
        result = flow.run(app["id"])
        self._summarize_reactive_result(result)

    def _show_status(self) -> None:
        """Menu option 4: status funnel."""
        flow = StatusFlow(self.tracker, self.config)
        flow.funnel()

    def _show_audit(self) -> None:
        """Menu option 5: audit trail."""
        flow = AuditFlow(self.tracker, self.config)

        recent = self.tracker.get_recent_applications(limit=20)
        if not recent:
            self.console.print("[yellow]No applications yet.[/yellow]")
            return

        table = Table(title="Recent applications")
        table.add_column("#", style="dim")
        table.add_column("ID", style="dim")
        table.add_column("Company", style="cyan")
        table.add_column("Role")
        table.add_column("Status", style="yellow")

        for i, app in enumerate(recent):
            table.add_row(
                str(i),
                str(app.get("id", ""))[:8],
                app.get("company", "")[:25],
                app.get("role", "")[:35],
                app.get("status", ""),
            )
        self.console.print(table)

        choice = Prompt.ask(
            "\n[bold]Pick an application to audit[/bold] "
            "(index or 'cancel')",
            default="cancel",
        )
        if choice == "cancel":
            return

        try:
            idx = int(choice)
            if idx < 0 or idx >= len(recent):
                return
        except ValueError:
            return

        flow.show(recent[idx]["id"])

    def _show_grades(self) -> None:
        """Menu option 6: grade distribution."""
        flow = StatusFlow(self.tracker, self.config)
        flow.grade_distribution()

    def _show_costs(self) -> None:
        """Menu option 7: cost report."""
        flow = StatusFlow(self.tracker, self.config)
        flow.cost_report()

    def _summarize_reactive_result(self, result: dict) -> None:
        """Print a summary of a reactive flow result."""
        status = result.get("status", "unknown")

        if status == "completed":
            self.console.print(Panel(
                f"[bold green]✓ Completed[/bold green]\n\n"
                f"Resume: {result.get('resume_pdf') or result.get('resume_tex')}\n"
                f"Score: {result.get('score', '?')}/13 "
                f"({result.get('grade', '?')})\n"
                f"Archetype: {result.get('archetype', '?')}",
                border_style="green",
            ))
        elif status == "scored_below_threshold":
            self.console.print(Panel(
                f"[yellow]Below threshold[/yellow]\n"
                f"Score {result.get('score')} / "
                f"{result.get('grade')}",
                border_style="yellow",
            ))
        elif status == "duplicate":
            self.console.print(Panel(
                f"[yellow]Duplicate URL[/yellow]\n"
                f"{result.get('url', '')}",
                border_style="yellow",
            ))
        elif status == "aborted":
            self.console.print(Panel(
                "[yellow]Aborted in coordinator[/yellow]\n"
                "Application saved at 'resume_tailored' status.",
                border_style="yellow",
            ))
        elif status == "user_skipped":
            self.console.print(Panel(
                f"[yellow]Skipped after scoring[/yellow]\n"
                f"Score {result.get('score')} / "
                f"{result.get('grade')}",
                border_style="yellow",
            ))
        elif status == "scrape_failed":
            self.console.print(Panel(
                f"[red]Scrape failed[/red]\n"
                f"{result.get('url', '')}",
                border_style="red",
            ))
        else:
            self.console.print(Panel(
                f"Status: {status}",
                border_style="dim",
            ))

    def run(self) -> int:
        """Main entry point. Returns exit code."""
        if not self.bootstrap():
            return 1

        self.show_banner()

        try:
            while True:
                choice = self.show_menu()
                cont = self.run_menu_choice(choice)
                if not cont:
                    break
        except KeyboardInterrupt:
            self.console.print("\n[dim]Goodbye.[/dim]")

        return 0


def main():
    """Module entry point — run with: uv run python main.py"""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    app = Shortlist()
    sys.exit(app.run())


if __name__ == "__main__":
    main()

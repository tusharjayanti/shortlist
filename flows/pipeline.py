from rich.console import Console
from rich.panel import Panel

from flows.reactive import ReactiveFlow
from tools.config_loader import Config
from tracker.tracker import JobTracker


class PipelineFlow:
    """
    Resume an application that was scored or partially processed
    but not fully completed. Picks up from wherever it left off.
    """

    def __init__(self, tracker: JobTracker, config: Config):
        self.tracker = tracker
        self.config = config
        self.console = Console()
        self.reactive = ReactiveFlow(tracker, config)

    def list_resumable(self) -> list[dict]:
        """Return applications in 'scored' or 'shortlisted' status."""
        return self.tracker.get_applications_by_status([
            "scored", "shortlisted",
        ])

    def run(self, app_id: str) -> dict:
        """Resume the given application from its current state."""
        app = self.tracker.get_application(app_id)
        if not app:
            self.console.print(
                f"[red]No application found: {app_id}[/red]"
            )
            return {"status": "not_found"}

        self.console.print(Panel.fit(
            f"[bold cyan]Resuming: "
            f"{app['company']} — {app['role']}[/bold cyan]\n"
            f"Current status: {app['status']}",
            border_style="cyan",
        ))

        if app.get("job_url"):
            return self.reactive.run(app["job_url"])

        self.console.print(
            "[yellow]Application has no URL. "
            "Paste the JD again to continue:[/yellow]"
        )
        return self.reactive.run("")

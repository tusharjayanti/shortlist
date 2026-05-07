from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tools.config_loader import Config
from tracker.tracker import JobTracker


class AuditFlow:
    """View the audit trail for a specific application."""

    def __init__(self, tracker: JobTracker, config: Config):
        self.tracker = tracker
        self.config = config
        self.console = Console()

    def show(self, app_id: str) -> list[dict]:
        """Pretty-print the audit log for an application."""
        logs = self.tracker.get_audit_logs_by_app(app_id)

        if not logs:
            self.console.print(
                f"[yellow]No audit logs for {app_id}[/yellow]"
            )
            return []

        app = self.tracker.get_application(app_id)
        if app:
            self.console.print(Panel.fit(
                f"[bold]{app['company']} — {app['role']}[/bold]\n"
                f"Status: {app.get('status', '?')}",
                border_style="cyan",
            ))

        table = Table(title=f"Audit trail ({len(logs)} entries)")
        table.add_column("Time", style="dim")
        table.add_column("Agent", style="cyan")
        table.add_column("Action", style="white")
        table.add_column("Tokens", justify="right")
        table.add_column("Latency (ms)", justify="right")
        table.add_column("Status")

        for log in logs:
            status_color = "green" if log.get("success") else "red"
            status_text = "✓" if log.get("success") else "✗"
            tokens = log.get("tokens_used") or 0
            table.add_row(
                str(log.get("timestamp", ""))[:19],
                str(log.get("agent", ""))[:14],
                str(log.get("action", ""))[:30],
                f"{tokens:,}",
                f"{log.get('latency_ms') or 0:,}",
                f"[{status_color}]{status_text}[/{status_color}]",
            )

        self.console.print(table)
        return logs

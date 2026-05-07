from rich.console import Console
from rich.table import Table

from tools.config_loader import Config
from tracker.tracker import JobTracker

# Anthropic Sonnet pricing (as of writing): $3/M input, $15/M output.
# audit_logs only stores the input+output sum (tokens_used), so we use a
# blended rate assuming a typical ~70/30 input/output split.
_BLENDED_PRICE_PER_M = 6.6


class StatusFlow:
    """Read-only reports on the application pipeline."""

    def __init__(self, tracker: JobTracker, config: Config):
        self.tracker = tracker
        self.config = config
        self.console = Console()

    def funnel(self) -> dict:
        """Conversion across pipeline stages."""
        rows = self.tracker.get_status_counts()

        ordered_statuses = [
            "discovered", "scored", "shortlisted",
            "resume_tailored", "cover_written", "approved",
            "applied", "interviewing", "offer",
            "rejected", "withdrawn",
        ]

        total = sum(rows.values())
        if total == 0:
            self.console.print("[yellow]No applications yet.[/yellow]")
            return {"total": 0}

        table = Table(title="Pipeline funnel")
        table.add_column("Status", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("% of total", justify="right")

        for status in ordered_statuses:
            count = rows.get(status, 0)
            pct = (count / total) * 100 if total else 0
            table.add_row(status, str(count), f"{pct:.1f}%")

        self.console.print(table)
        return {"total": total, "by_status": dict(rows)}

    def grade_distribution(self) -> dict:
        """How many A/B/C/D/F have we scored?"""
        rows = self.tracker.get_grade_counts()

        table = Table(title="Grade distribution")
        table.add_column("Grade")
        table.add_column("Count", justify="right")

        for grade in ["A", "B", "C", "D", "F"]:
            table.add_row(grade, str(rows.get(grade, 0)))

        self.console.print(table)
        return rows

    def cost_report(self) -> dict:
        """Total tokens used and estimated cost (blended price)."""
        rows = self.tracker.get_token_usage_by_agent()

        table = Table(title="Cost report")
        table.add_column("Agent", style="cyan")
        table.add_column("Calls", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("Est cost ($)", justify="right")

        total_cost = 0.0
        for agent, stats in rows.items():
            cost = stats["total_tokens"] / 1_000_000 * _BLENDED_PRICE_PER_M
            total_cost += cost
            table.add_row(
                agent,
                str(stats["calls"]),
                f"{stats['total_tokens']:,}",
                f"${cost:.3f}",
            )

        self.console.print(table)
        self.console.print(
            f"[bold]Total estimated cost: ${total_cost:.3f}[/bold]"
        )
        return {"total_cost": total_cost, "by_agent": rows}

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from agents.cover import CoverLetterAgent
from agents.networker import NetworkerAgent
from agents.tailor import TailorAgent
from tools.config_loader import Config
from tools.schemas import (
    CoverLetter,
    NetworkingMessages,
    ReviewResult,
)
from tracker.tracker import JobTracker


class ArtifactStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"


@dataclass
class ArtifactState:
    name: str
    status: ArtifactStatus = ArtifactStatus.PENDING
    current_version: int = 1
    feedback_history: list[str] = field(default_factory=list)
    last_output: object = None


class ReviewCoordinator:
    """
    Manages the human-in-the-loop iteration for tailor, cover
    letter, and networking messages.

    Flow:
      1. All three artifacts produced (tailor + cover + networker)
      2. Show resume diff first; user approves or gives feedback
      3. If feedback, re-run tailor with feedback; re-show diff
      4. Once resume approved, show cover letter
      5. Iterate until cover letter approved
      6. Once cover letter approved, show networking messages
      7. Iterate until networking approved
      8. Return when all three are APPROVED

    User can:
      - Type "y" or "yes" to approve current artifact
      - Type "n: <feedback>" to reject with feedback
      - Type "abort" to cancel the whole review
    """

    def __init__(
        self,
        tracker: JobTracker,
        config: Config,
        tailor: TailorAgent,
        cover: CoverLetterAgent,
        networker: NetworkerAgent,
    ):
        self.tracker = tracker
        self.config = config
        self.tailor = tailor
        self.cover = cover
        self.networker = networker
        self.console = Console()

    def run(
        self,
        app_id: str,
        job: dict,
        archetype: str,
        review: ReviewResult,
    ) -> dict:
        """
        Run the full review loop. Returns dict with:
          resume_path: str (final approved tex path)
          cover_letter: CoverLetter (approved version)
          networking: NetworkingMessages (approved version)
          aborted: bool
        """
        self.console.print(Panel.fit(
            f"[bold]Review session: {job['company']} — {job['title']}[/bold]",
            border_style="cyan",
        ))

        self.console.print("\n[dim]Generating initial artifacts...[/dim]")

        resume_state = ArtifactState(name="resume")
        cover_state = ArtifactState(name="cover_letter")
        networking_state = ArtifactState(name="networking")

        resume_state.last_output = self.tailor.run(
            app_id, job, archetype, review,
        )
        cover_state.last_output = self.cover.run(
            app_id, job, archetype,
        )
        networking_state.last_output = self.networker.run(
            app_id, job, archetype,
        )

        for state, agent_runner, render_fn in [
            (resume_state, self._rerun_tailor, self._render_resume),
            (cover_state, self._rerun_cover, self._render_cover),
            (networking_state, self._rerun_networker, self._render_networking),
        ]:
            aborted = self._iterate_on_artifact(
                state, agent_runner, render_fn,
                app_id, job, archetype, review,
            )
            if aborted:
                return {
                    "resume_path": None,
                    "cover_letter": None,
                    "networking": None,
                    "aborted": True,
                }

        self.console.print(Panel.fit(
            "[bold green]✓ All three artifacts approved.[/bold green]",
            border_style="green",
        ))

        return {
            "resume_path": resume_state.last_output["tex_path"],
            "cover_letter": cover_state.last_output,
            "networking": networking_state.last_output,
            "aborted": False,
        }

    def _iterate_on_artifact(
        self,
        state: ArtifactState,
        rerun_fn: Callable,
        render_fn: Callable,
        app_id: str,
        job: dict,
        archetype: str,
        review: ReviewResult,
    ) -> bool:
        """
        Iterate on a single artifact until approved or aborted.
        Returns True if user aborted, False otherwise.
        """
        while state.status != ArtifactStatus.APPROVED:
            self.console.rule(
                f"[bold]Artifact: {state.name} (v{state.current_version})[/bold]"
            )
            render_fn(state.last_output)

            response = Prompt.ask(
                "\n[bold cyan]Approve?[/bold cyan]\n"
                "  [green]y[/green]  approve\n"
                "  [yellow]n: <feedback>[/yellow]  give feedback\n"
                "  [red]abort[/red]  cancel review\n"
                "Choice"
            ).strip()

            if response.lower() in ("y", "yes"):
                state.status = ArtifactStatus.APPROVED
                self.console.print(
                    f"[green]✓ {state.name} approved (v{state.current_version})[/green]"
                )
                continue

            if response.lower() == "abort":
                self.console.print("[red]Review aborted.[/red]")
                return True

            if response.lower().startswith("n:") or response.lower().startswith("n "):
                feedback = response[2:].strip().lstrip(":").strip()
                if not feedback:
                    self.console.print(
                        "[yellow]Feedback cannot be empty. Try again.[/yellow]"
                    )
                    continue

                state.feedback_history.append(feedback)
                state.status = ArtifactStatus.NEEDS_REVISION
                state.current_version += 1

                self.console.print(
                    f"\n[dim]Re-running {state.name} with feedback...[/dim]"
                )
                state.last_output = rerun_fn(
                    app_id, job, archetype, review, feedback,
                )
                state.status = ArtifactStatus.PENDING
                continue

            self.console.print(
                "[yellow]Unrecognized input. Use 'y', 'n: <feedback>', or 'abort'.[/yellow]"
            )

        return False

    # Rerun functions for each agent

    def _rerun_tailor(self, app_id, job, archetype, review, feedback):
        return self.tailor.run(
            app_id, job, archetype, review, feedback=feedback,
        )

    def _rerun_cover(self, app_id, job, archetype, review, feedback):
        return self.cover.run(
            app_id, job, archetype, feedback=feedback,
        )

    def _rerun_networker(self, app_id, job, archetype, review, feedback):
        return self.networker.run(
            app_id, job, archetype, feedback=feedback,
        )

    # Render functions for each artifact

    def _render_resume(self, output: dict) -> None:
        self.console.print(Panel(
            f"[bold]File:[/bold] {output['tex_path']}\n"
            f"[bold]Summary:[/bold] {output['changes_summary']}\n\n"
            f"[dim]Open the .tex file in your editor to review the full content.[/dim]",
            title="Tailored Resume",
            border_style="blue",
        ))

    def _render_cover(self, letter: CoverLetter) -> None:
        self.console.print(Panel(
            f"[bold]Strategy angle:[/bold]\n{letter.angle}\n\n"
            f"[bold]Selected proof points:[/bold]\n"
            + "\n".join(f"  • {pid}" for pid in letter.selected_proof_point_ids)
            + f"\n\n[bold]Word count:[/bold] {letter.word_count}\n\n"
            f"[bold]Letter:[/bold]\n{letter.text}",
            title="Cover Letter",
            border_style="magenta",
        ))

    def _render_networking(self, msgs: NetworkingMessages) -> None:
        self.console.print(Panel(
            f"[bold]Strategy angle:[/bold]\n{msgs.angle}\n\n"
            f"[bold]Selected proof points:[/bold]\n"
            + "\n".join(f"  • {pid}" for pid in msgs.selected_proof_point_ids)
            + f"\n\n[bold]Placeholders:[/bold] {', '.join(msgs.placeholders_used)}\n\n"
            f"[bold cyan]LinkedIn DM[/bold cyan] ({msgs.linkedin_dm_word_count} words):\n{msgs.linkedin_dm}\n\n"
            f"[bold cyan]Cold Email[/bold cyan] ({msgs.cold_email_word_count} words):\n"
            f"Subject: {msgs.cold_email_subject}\n\n{msgs.cold_email_body}",
            title="Networking Messages",
            border_style="yellow",
        ))

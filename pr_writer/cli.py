import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .ai_client import stream_pr_description
from .git_utils import Platform, collect_git_context
from .platforms import PlatformError, push_description

console = Console()


def _load_env() -> None:
    load_dotenv()
    load_dotenv(Path.home() / ".pr-writer" / ".env")


@click.command()
@click.option("--base", "-b", default="main", show_default=True, help="Base branch to compare against.")
@click.option("--repo", "-r", default=".", show_default=True, help="Path to the git repository.")
@click.option("--copy", "-c", is_flag=True, help="Copy the generated description to clipboard.")
@click.option("--push", "-p", is_flag=True, help="Update the open PR on GitHub/Gitea with the description.")
@click.option("--raw", is_flag=True, help="Print raw Markdown without the formatted preview panel.")
@click.version_option(version="0.1.0")
def main(base: str, repo: str, copy: bool, push: bool, raw: bool) -> None:
    """Generate AI-powered PR descriptions from your git diff.

    \b
    Reads your local git history, sends the context to Claude, and streams
    back a structured PR description. Supports GitHub and Gitea remotes.

    \b
    Examples:
      pr-writer                      # compare current branch vs main
      pr-writer --base develop       # compare vs develop
      pr-writer --copy               # copy output to clipboard
      pr-writer --push               # update the open PR description via API
    """
    _load_env()

    if not os.getenv("ANTHROPIC_API_KEY"):
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY is not set.")
        console.print("Add it to a [bold].env[/bold] file in your project or home directory.")
        sys.exit(1)

    # ── Collect git context ──────────────────────────────────────────────────
    with console.status("[bold blue]Reading git context...", spinner="dots"):
        try:
            ctx = collect_git_context(repo, base)
        except RuntimeError as exc:
            console.print(f"[red]Git error:[/red] {exc}")
            sys.exit(1)

    if not ctx.commits and not ctx.diff:
        console.print(
            f"[yellow]No changes[/yellow] between "
            f"[bold]{ctx.current_branch}[/bold] and [bold]{base}[/bold]."
        )
        sys.exit(0)

    # ── Print summary line ───────────────────────────────────────────────────
    remote_label = ""
    if ctx.remote:
        platform_name = "GitHub" if ctx.remote.platform == Platform.GITHUB else "Gitea"
        remote_label = (
            f"  [dim]Remote:[/dim] {platform_name} "
            f"([dim]{ctx.remote.owner}/{ctx.remote.repo}[/dim])"
        )

    console.print(
        f"[dim]Branch:[/dim] [bold cyan]{ctx.current_branch}[/bold cyan] → [bold]{base}[/bold]"
        f"  [dim]Commits:[/dim] {len(ctx.commits)}"
        f"  [dim]Files:[/dim] {len(ctx.changed_files)}"
        + remote_label
    )
    console.print()

    # ── Stream description from Claude ───────────────────────────────────────
    console.print("[bold green]Generating PR description[/bold green]\n")
    parts: list[str] = []
    try:
        for token in stream_pr_description(ctx):
            console.print(token, end="")
            parts.append(token)
    except Exception as exc:
        console.print(f"\n[red]API error:[/red] {exc}")
        sys.exit(1)

    description = "".join(parts)
    console.print("\n")

    # ── Formatted preview ────────────────────────────────────────────────────
    if not raw:
        console.print(
            Panel(
                Markdown(description),
                title="[bold]Formatted Preview[/bold]",
                border_style="dim",
            )
        )

    # ── Copy to clipboard ────────────────────────────────────────────────────
    if copy:
        try:
            import pyperclip  # noqa: PLC0415
            pyperclip.copy(description)
            console.print("[green]Copied to clipboard.[/green]")
        except Exception as exc:
            console.print(f"[yellow]Could not copy to clipboard:[/yellow] {exc}")

    # ── Push to platform ─────────────────────────────────────────────────────
    if push:
        with console.status("[bold blue]Updating PR description...", spinner="dots"):
            try:
                pr_url = push_description(ctx, description)
            except PlatformError as exc:
                console.print(f"[red]Push failed:[/red] {exc}")
                sys.exit(1)
        console.print(f"[green]PR description updated:[/green] {pr_url}")

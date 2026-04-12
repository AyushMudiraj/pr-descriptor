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


def _ensure_platform_token(ctx_git) -> None:
    """Prompt for GitHub/Gitea token on first --push use, validate, and save it."""
    import requests
    from .setup_wizard import ENV_PATH, _save_key

    if ctx_git.remote is None:
        return  # push_description will raise PlatformError with a clear message

    if ctx_git.remote.platform == Platform.GITHUB:
        env_var = "GITHUB_TOKEN"
        platform_name = "GitHub"
        key_url = "https://github.com/settings/tokens/new?description=pr-descriptor&scopes=repo"
    else:
        env_var = "GITEA_TOKEN"
        platform_name = "Gitea"
        key_url = None

    if os.getenv(env_var):
        return  # already configured

    console.print(
        f"\n[yellow]No {env_var} found.[/yellow] "
        f"This is needed to update your PR via the {platform_name} API.\n"
        f"[dim]It will be saved to ~/.pr-writer/.env for future use.[/dim]\n"
    )
    if key_url:
        console.print(f"[dim]Generate one at:[/dim] [cyan]{key_url}[/cyan]\n")

    while True:
        token = click.prompt(
            f"Paste your {platform_name} token",
            hide_input=True,
            prompt_suffix=": ",
        ).strip()

        if not token:
            console.print("[red]No token entered. Cannot push.[/red]")
            sys.exit(1)

        # Validate the token with a lightweight API call
        if env_var == "GITHUB_TOKEN":
            console.print("[dim]Validating token...[/dim]", end=" ")
            try:
                resp = requests.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                    },
                    timeout=10,
                )
                if resp.status_code == 401:
                    console.print("[red]Invalid token.[/red] Please check and try again.")
                    if not click.confirm("Try a different token?", default=True):
                        sys.exit(1)
                    continue
                console.print("[green]Valid![/green]")
            except Exception:
                console.print("[yellow]Could not validate (network error) — saving anyway.[/yellow]")
        else:
            # Gitea: skip validation, just save
            pass

        first_write = not ENV_PATH.exists()
        _save_key(env_var, token)
        os.environ[env_var] = token
        if first_write:
            console.print(
                f"[green]{env_var} saved.[/green] "
                f"[dim]A new config file was created at [bold]{ENV_PATH}[/bold] — "
                f"you can view or edit it there.[/dim]\n"
            )
        else:
            console.print(f"[green]{env_var} saved to {ENV_PATH}[/green]\n")
        break


@click.group(invoke_without_command=True)
@click.option("--base", "-b", default="main", show_default=True, help="Base branch to compare against.")
@click.option("--repo", "-r", default=".", show_default=True, help="Path to the git repository.")
@click.option("--copy", "-c", is_flag=True, help="Copy the generated description to clipboard.")
@click.option("--push", "-p", is_flag=True, help="Update the open PR on GitHub/Gitea with the description.")
@click.option("--raw", is_flag=True, help="Print raw Markdown without the formatted preview panel.")
@click.version_option(version="0.1.3")
@click.pass_context
def main(ctx: click.Context, base: str, repo: str, copy: bool, push: bool, raw: bool) -> None:
    """Generate AI-powered PR descriptions from your git diff.

    \b
    Reads your local git history, sends the context to an AI provider, and
    streams back a structured PR description. Automatically falls back across
    providers (Claude -> Gemini -> Groq -> Mistral) if one hits its quota.

    \b
    Run 'pr-descriptor setup' first to configure your API keys.

    \b
    Examples:
      pr-descriptor                      # compare current branch vs main
      pr-descriptor --base develop       # compare vs develop
      pr-descriptor --copy               # copy output to clipboard
      pr-descriptor --push               # update the open PR description via API
    """
    if ctx.invoked_subcommand is not None:
        return

    _load_env()

    has_key = any(os.getenv(k) for k in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY", "GEMINI_API_KEY"))
    if not has_key:
        console.print("[red]No API keys configured.[/red]")
        console.print("Run [bold cyan]pr-descriptor setup[/bold cyan] to get started.")
        sys.exit(1)

    # ── Collect git context ──────────────────────────────────────────────────
    with console.status("[bold blue]Reading git context...", spinner="dots"):
        try:
            ctx_git = collect_git_context(repo, base)
        except RuntimeError as exc:
            console.print(f"[red]Git error:[/red] {exc}")
            sys.exit(1)

    if not ctx_git.commits and not ctx_git.diff:
        console.print(
            f"[yellow]No changes[/yellow] between "
            f"[bold]{ctx_git.current_branch}[/bold] and [bold]{base}[/bold]."
        )
        sys.exit(0)

    # ── Print summary line ───────────────────────────────────────────────────
    remote_label = ""
    if ctx_git.remote:
        platform_name = "GitHub" if ctx_git.remote.platform == Platform.GITHUB else "Gitea"
        remote_label = (
            f"  [dim]Remote:[/dim] {platform_name} "
            f"([dim]{ctx_git.remote.owner}/{ctx_git.remote.repo}[/dim])"
        )

    console.print(
        f"[dim]Branch:[/dim] [bold cyan]{ctx_git.current_branch}[/bold cyan] -> [bold]{base}[/bold]"
        f"  [dim]Commits:[/dim] {len(ctx_git.commits)}"
        f"  [dim]Files:[/dim] {len(ctx_git.changed_files)}"
        + remote_label
    )
    console.print()

    # ── Stream description ───────────────────────────────────────────────────
    console.print("[bold green]Generating PR description[/bold green]\n")
    parts: list[str] = []
    try:
        for token in stream_pr_description(ctx_git):
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
            import pyperclip
            pyperclip.copy(description)
            console.print("[green]Copied to clipboard.[/green]")
        except Exception as exc:
            console.print(f"[yellow]Could not copy to clipboard:[/yellow] {exc}")

    # ── Push to platform ─────────────────────────────────────────────────────
    if push:
        _ensure_platform_token(ctx_git)
        with console.status("[bold blue]Updating PR description...", spinner="dots"):
            try:
                pr_url = push_description(ctx_git, description)
            except PlatformError as exc:
                console.print(f"[red]Push failed:[/red] {exc}")
                sys.exit(1)
        console.print(f"[green]PR description updated:[/green] {pr_url}")


@main.command()
def setup() -> None:
    """Interactive setup wizard to configure AI provider API keys."""
    from .setup_wizard import run_setup
    run_setup()

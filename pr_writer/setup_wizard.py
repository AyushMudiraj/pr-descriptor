import webbrowser
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.rule import Rule

console = Console()

ENV_PATH = Path.home() / ".pr-writer" / ".env"


# ── Key validators ────────────────────────────────────────────────────────────

def _validate_groq(key: str) -> str:
    """Returns 'ok', 'invalid', or 'limited'."""
    try:
        from groq import AuthenticationError, Groq
        client = Groq(api_key=key)
        client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        return "ok"
    except AuthenticationError:
        return "invalid"
    except Exception:
        return "limited"


def _validate_mistral(key: str) -> str:
    try:
        from mistralai.client import Mistral
        client = Mistral(api_key=key)
        client.chat.complete(
            model="mistral-small-latest",
            messages=[{"role": "user", "content": "hi"}],
        )
        return "ok"
    except Exception as e:
        # 401/403 = bad key, 429 = quota (still valid key)
        status = getattr(e, "status_code", None)
        if status in (401, 403):
            return "invalid"
        return "limited"


def _validate_claude(key: str) -> str:
    try:
        from anthropic import Anthropic, AuthenticationError
        client = Anthropic(api_key=key)
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return "ok"
    except AuthenticationError:
        return "invalid"
    except Exception as e:
        if "credit" in str(e).lower() or "balance" in str(e).lower():
            return "limited"
        return "limited"


def _validate_gemini(key: str) -> str:
    try:
        import google.generativeai as genai
        from google.api_core.exceptions import PermissionDenied
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash-lite")
        model.generate_content("hi")
        return "ok"
    except PermissionDenied:
        return "invalid"
    except Exception:
        return "limited"


# ── .env helpers ──────────────────────────────────────────────────────────────

def _save_key(env_var: str, key: str) -> None:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    for i, line in enumerate(lines):
        if line.startswith(f"{env_var}="):
            lines[i] = f"{env_var}={key}"
            break
    else:
        lines.append(f"{env_var}={key}")
    ENV_PATH.write_text("\n".join(lines) + "\n")


def _get_existing_key(env_var: str) -> Optional[str]:
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith(f"{env_var}="):
            val = line.split("=", 1)[1].strip()
            return val if val else None
    return None


# ── Provider config ───────────────────────────────────────────────────────────

PROVIDERS = [
    {
        "name": "Claude (Anthropic)",
        "env_var": "ANTHROPIC_API_KEY",
        "free": False,
        "tagline": "paid • best quality • requires credits",
        "url": "https://console.anthropic.com/settings/keys",
        "validate": _validate_claude,
    },
    {
        "name": "Gemini (Google)",
        "env_var": "GEMINI_API_KEY",
        "free": False,
        "tagline": "paid • requires Google Cloud billing",
        "url": "https://aistudio.google.com/app/apikey",
        "validate": _validate_gemini,
    },
    {
        "name": "Groq",
        "env_var": "GROQ_API_KEY",
        "free": True,
        "tagline": "free • ~14,400 req/day • Llama 3.3",
        "url": "https://console.groq.com/keys",
        "validate": _validate_groq,
    },
    {
        "name": "Mistral",
        "env_var": "MISTRAL_API_KEY",
        "free": True,
        "tagline": "free • EU-based (GDPR) • Mistral Small",
        "url": "https://console.mistral.ai/api-keys",
        "validate": _validate_mistral,
    },
]


# ── Main wizard ───────────────────────────────────────────────────────────────

def run_setup() -> None:
    console.print()
    console.print(Rule("[bold cyan]pr-descriptor setup[/bold cyan]"))
    console.print(
        "\nThis wizard will configure your AI provider keys.\n"
        "Keys are saved to [bold]~/.pr-writer/.env[/bold] and work from any project.\n"
        "\nProviders are used in this priority order: "
        "[bold]Claude -> Gemini -> Groq -> Mistral[/bold]\n"
    )

    configured = []

    for provider in PROVIDERS:
        name = provider["name"]
        env_var = provider["env_var"]
        free = provider["free"]
        tagline = provider["tagline"]
        url = provider["url"]
        validate = provider["validate"]

        console.print(Rule(f"[bold]{name}[/bold]  [dim]{tagline}[/dim]"))

        # Check if already configured
        existing = _get_existing_key(env_var)
        if existing:
            console.print(f"[green]Already configured.[/green] Skip and keep existing? ", end="")
            if click.confirm("", default=True):
                configured.append(name)
                console.print()
                continue

        # For paid providers, ask if they have an account
        if not free:
            console.print(f"\nDo you have a paid [bold]{name}[/bold] account with credits/billing enabled?")
            if not click.confirm("", default=False):
                console.print("[dim]Skipped.[/dim]\n")
                continue

        # Guide through key creation
        console.print(f"\n[bold]Step 1:[/bold] Opening [cyan]{url}[/cyan] in your browser...")
        webbrowser.open(url)
        console.print("[dim]Sign in and create a new API key.[/dim]")
        click.pause(info="\nPress Enter once you have your key ready...")

        # Key input loop
        while True:
            key = click.prompt(
                f"\nPaste your {name} API key",
                hide_input=True,
                prompt_suffix=": ",
            )
            key = key.strip()
            if not key:
                console.print("[yellow]No key entered. Skipping.[/yellow]")
                break

            console.print("[dim]Validating key...[/dim]", end=" ")
            status = validate(key)

            if status == "ok":
                first_write = not ENV_PATH.exists()
                _save_key(env_var, key)
                if first_write:
                    console.print(
                        f"[green]Valid! Key saved.[/green] "
                        f"[dim]A new config file was created at [bold]{ENV_PATH}[/bold] — "
                        f"you can view or edit it there.[/dim]"
                    )
                else:
                    console.print(f"[green]Valid! Key saved to {ENV_PATH}[/green]")
                configured.append(name)
                break
            elif status == "limited":
                first_write = not ENV_PATH.exists()
                _save_key(env_var, key)
                if first_write:
                    console.print(
                        f"[yellow]Key saved.[/yellow] "
                        f"[dim]A new config file was created at [bold]{ENV_PATH}[/bold] — "
                        f"you can view or edit it there.\n"
                        f"(Note: quota/credits may be limited — will activate when available)[/dim]"
                    )
                else:
                    console.print(
                        f"[yellow]Key saved to {ENV_PATH}[/yellow] "
                        f"[dim](Note: quota/credits may be limited — will activate when available)[/dim]"
                    )
                configured.append(name)
                break
            else:
                console.print("[red]Invalid key.[/red] Please check and try again.")
                if not click.confirm("Try a different key?", default=True):
                    break

        console.print()

    # Summary
    console.print(Rule("[bold]Setup complete[/bold]"))
    if configured:
        console.print(f"\n[green]Configured providers:[/green] {', '.join(configured)}")
        console.print("\nRun [bold cyan]pr-descriptor[/bold cyan] inside any git repo to generate a PR description.")
    else:
        console.print(
            "\n[yellow]No providers configured.[/yellow] "
            "Run [bold]pr-descriptor setup[/bold] again to add keys."
        )
    console.print()

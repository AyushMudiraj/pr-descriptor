# pr-descriptor

AI-powered pull request description generator. Point it at any git repository and it instantly writes a structured, professional PR description from your branch diff.

Automatically falls back across AI providers — if one hits its quota, it switches to the next one silently.

## Installation

```bash
pip install pr-descriptor
```

## First-time Setup

Run the interactive setup wizard once after installing:

```bash
pr-descriptor setup
```

The wizard will:
- Open your browser to each provider's API key page
- Ask you to paste the key into the terminal
- Validate the key with a quick test call
- Save it automatically to `~/.pr-writer/.env`

You only need to do this **once**. The same keys work on any machine — just run `pr-descriptor setup` again on a new machine and paste the same keys.

### Providers

The wizard guides you through all four providers in this order:

| Provider | Cost | Notes |
|---|---|---|
| Claude (Anthropic) | Paid (requires credits) | Best quality |
| Gemini (Google) | Paid (requires billing) | Google Cloud |
| Groq | Free (~14,400 req/day) | Free fallback |
| Mistral | Free (EU-based, GDPR) | Free fallback |

You need **at least one** provider configured. Groq and Mistral are free and require no credit card.

## Usage

Run inside any git repository on a feature branch:

```bash
pr-descriptor
```

### Options

```
-b, --base TEXT    Base branch to compare against  [default: main]
-r, --repo TEXT    Path to the git repository      [default: .]
-c, --copy         Copy the output to clipboard
-p, --push         Update the open PR on GitHub/Gitea via API
    --raw          Print raw Markdown (no formatted preview panel)
    --version      Show version
    --help         Show help
```

### Examples

```bash
# Basic — compare current branch vs main
pr-descriptor

# Compare against a different base branch
pr-descriptor --base develop

# Copy the output directly to clipboard
pr-descriptor --copy

# Update the open PR on GitHub with the generated description
pr-descriptor --push

# Print raw Markdown (useful for piping or scripting)
pr-descriptor --raw

# Run on a repo from a different directory
pr-descriptor --repo /path/to/your/repo --base main
```

## How It Works

```
Your feature branch
        |
        v
git log + git diff (vs base branch)
        |
        v
AI generates structured PR description
        |
        v
Streamed to your terminal in real time
```

### Provider Fallback

Providers are tried in this priority order based on which keys you have configured:

```
Claude  ->  Gemini  ->  Groq  ->  Mistral
```

If a provider hits its rate limit or quota, the next one is used automatically with no action needed from you.

## Output Format

Every generated description follows this structure:

```markdown
## Summary
What this PR does and why.

## Changes
- Key changes as bullet points

## Testing
How to test the changes.

## Breaking Changes
Any breaking changes, or "None".

## Related Issues
Issue references from commits, or "None".
```

## Supported Platforms

- **GitHub** — auto-detected from remote URL
- **Gitea** — auto-detected from remote URL

When using `--push`, the tool updates the open PR description via the platform API. Requires a `GITHUB_TOKEN` or `GITEA_TOKEN` in your `~/.pr-writer/.env`.

## Requirements

- Python 3.10+
- Git installed and on PATH
- At least one AI provider API key (configured via `pr-descriptor setup`)

from typing import Iterator

from anthropic import Anthropic

from .git_utils import GitContext

SYSTEM_PROMPT = """\
You are an expert software engineer who writes clear, concise, and professional pull request descriptions.

Given git context (branch name, commits, changed files, diff), generate a well-structured PR description \
in GitHub-flavored Markdown using this exact format:

## Summary
A concise paragraph explaining what this PR does and the motivation behind it.

## Changes
- Bullet points listing the key changes

## Testing
Steps or notes on how to test these changes.

## Breaking Changes
List any breaking changes, or write "None" if there are none.

## Related Issues
Reference issue numbers mentioned in commits (e.g., Fixes #123), or write "None".

Be specific and professional. Focus on the *why* as much as the *what*. No filler phrases.\
"""


def _build_prompt(ctx: GitContext) -> str:
    commits = "\n".join(ctx.commits) if ctx.commits else "No commits"
    files = "\n".join(ctx.changed_files) if ctx.changed_files else "No changed files"
    return (
        f"Branch: `{ctx.current_branch}` → `{ctx.base_branch}`\n\n"
        f"Commits:\n{commits}\n\n"
        f"Changed files:\n{files}\n\n"
        f"Diff:\n```diff\n{ctx.diff}\n```"
    )


def stream_pr_description(ctx: GitContext) -> Iterator[str]:
    """Stream the PR description token by token from Claude."""
    client = Anthropic()
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_prompt(ctx)}],
    ) as stream:
        for text in stream.text_stream:
            yield text

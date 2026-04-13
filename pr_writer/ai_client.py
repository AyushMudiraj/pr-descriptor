import os
from typing import Iterator, Optional

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


class _ProviderExhausted(Exception):
    """Raised when a provider's quota/auth fails — triggers fallback."""
    def __init__(self, provider: str, cause: Exception):
        self.provider = provider
        super().__init__(f"{provider} unavailable: {cause}")


def _build_prompt(ctx: GitContext) -> str:
    commits = "\n".join(ctx.commits) if ctx.commits else "No commits"
    files = "\n".join(ctx.changed_files) if ctx.changed_files else "No changed files"
    return (
        f"Branch: `{ctx.current_branch}` -> `{ctx.base_branch}`\n\n"
        f"Commits:\n{commits}\n\n"
        f"Changed files:\n{files}\n\n"
        f"Diff:\n```diff\n{ctx.diff}\n```"
    )


def _stream_claude(key: str, prompt: str) -> Iterator[str]:
    from anthropic import Anthropic, AuthenticationError, RateLimitError
    try:
        client = Anthropic(api_key=key)
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield text
    except (AuthenticationError, RateLimitError) as e:
        raise _ProviderExhausted("Claude", e)


def _stream_groq(key: str, prompt: str) -> Iterator[str]:
    try:
        from groq import AuthenticationError, Groq, RateLimitError
        client = Groq(api_key=key)
        stream = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            stream=True,
        )
        for chunk in stream:
            yield chunk.choices[0].delta.content or ""
    except (AuthenticationError, RateLimitError) as e:
        raise _ProviderExhausted("Groq", e)


def _stream_mistral(key: str, prompt: str) -> Iterator[str]:
    try:
        from mistralai.client import Mistral
        client = Mistral(api_key=key)
        stream = client.chat.stream(
            model="mistral-small-latest",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        for chunk in stream:
            yield chunk.data.choices[0].delta.content or ""
    except Exception as e:
        # Use HTTP status code — more reliable than string matching
        if getattr(e, "status_code", None) in (401, 403, 429):
            raise _ProviderExhausted("Mistral", e)
        raise


def _stream_gemini(key: str, prompt: str) -> Iterator[str]:
    try:
        import google.generativeai as genai
        from google.api_core.exceptions import (
            InvalidArgument,
            NotFound,
            PermissionDenied,
            ResourceExhausted,
        )
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash-lite", system_instruction=SYSTEM_PROMPT)
        for chunk in model.generate_content(prompt, stream=True):
            if chunk.text:
                yield chunk.text
    except (ResourceExhausted, PermissionDenied, NotFound, InvalidArgument) as e:
        raise _ProviderExhausted("Gemini", e)


# Priority order: Claude -> Gemini -> Groq -> Mistral
_PROVIDERS = [
    ("Claude",  "ANTHROPIC_API_KEY", _stream_claude),
    ("Gemini",  "GEMINI_API_KEY",    _stream_gemini),
    ("Groq",    "GROQ_API_KEY",      _stream_groq),
    ("Mistral", "MISTRAL_API_KEY",   _stream_mistral),
]


def stream_pr_description(ctx: GitContext) -> Iterator[str]:
    """Stream PR description, falling back across providers if one is exhausted."""
    prompt = _build_prompt(ctx)
    last_error: Optional[Exception] = None

    for name, env_var, stream_fn in _PROVIDERS:
        key = os.getenv(env_var)
        if not key:
            continue  # key not configured, skip silently

        try:
            gen = stream_fn(key, prompt)
            first = next(gen)  # forces the HTTP request — catches auth/quota errors early
        except _ProviderExhausted as e:
            last_error = e
            continue
        except StopIteration:
            return  # empty response

        yield first
        yield from gen
        return  # success

    if last_error:
        raise RuntimeError(f"All providers exhausted. Last error: {last_error}")
    raise RuntimeError(
        "No API keys configured. Set at least one of: "
        "ANTHROPIC_API_KEY, GROQ_API_KEY, MISTRAL_API_KEY, GEMINI_API_KEY"
    )

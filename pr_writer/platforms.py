import os
from typing import Optional

import requests

from .git_utils import GitContext, Platform, RemoteInfo


class PlatformError(Exception):
    pass


# ---------------------------------------------------------------------------
# Header helpers
# ---------------------------------------------------------------------------

def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gitea_headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# PR lookup
# ---------------------------------------------------------------------------

def _find_github_pr(remote: RemoteInfo, branch: str, token: str) -> Optional[int]:
    url = f"https://api.github.com/repos/{remote.owner}/{remote.repo}/pulls"
    resp = requests.get(
        url,
        headers=_github_headers(token),
        params={"state": "open", "head": f"{remote.owner}:{branch}"},
        timeout=10,
    )
    resp.raise_for_status()
    prs = resp.json()
    return prs[0]["number"] if prs else None


def _find_gitea_pr(remote: RemoteInfo, branch: str, token: str) -> Optional[int]:
    url = f"https://{remote.host}/api/v1/repos/{remote.owner}/{remote.repo}/pulls"
    resp = requests.get(
        url,
        headers=_gitea_headers(token),
        params={"state": "open", "limit": 50},
        timeout=10,
    )
    resp.raise_for_status()
    for pr in resp.json():
        head = pr.get("head", {})
        if head.get("ref") == branch or head.get("label") == branch:
            return pr["number"]
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def push_description(ctx: GitContext, description: str) -> str:
    """
    Find the open PR for the current branch and update its description.
    Returns the PR URL on success. Raises PlatformError on failure.
    """
    remote = ctx.remote
    if remote is None:
        raise PlatformError("Could not detect a git remote. Is 'origin' set?")

    if remote.platform == Platform.GITHUB:
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise PlatformError("GITHUB_TOKEN is not set in your environment.")

        pr_number = _find_github_pr(remote, ctx.current_branch, token)
        if pr_number is None:
            raise PlatformError(
                f"No open PR found for branch '{ctx.current_branch}' "
                f"on {remote.owner}/{remote.repo}."
            )

        url = f"https://api.github.com/repos/{remote.owner}/{remote.repo}/pulls/{pr_number}"
        resp = requests.patch(
            url, headers=_github_headers(token), json={"body": description}, timeout=10
        )
        resp.raise_for_status()
        return f"https://github.com/{remote.owner}/{remote.repo}/pull/{pr_number}"

    else:  # Gitea
        token = os.getenv("GITEA_TOKEN")
        if not token:
            raise PlatformError("GITEA_TOKEN is not set in your environment.")

        pr_number = _find_gitea_pr(remote, ctx.current_branch, token)
        if pr_number is None:
            raise PlatformError(
                f"No open PR found for branch '{ctx.current_branch}' "
                f"on {remote.owner}/{remote.repo}."
            )

        url = f"https://{remote.host}/api/v1/repos/{remote.owner}/{remote.repo}/pulls/{pr_number}"
        resp = requests.patch(
            url, headers=_gitea_headers(token), json={"body": description}, timeout=10
        )
        resp.raise_for_status()
        return f"https://{remote.host}/{remote.owner}/{remote.repo}/pulls/{pr_number}"

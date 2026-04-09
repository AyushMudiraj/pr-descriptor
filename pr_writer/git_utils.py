import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional


class Platform(Enum):
    GITHUB = "github"
    GITEA = "gitea"
    UNKNOWN = "unknown"


@dataclass
class RemoteInfo:
    platform: Platform
    host: str
    owner: str
    repo: str
    url: str


@dataclass
class GitContext:
    current_branch: str
    base_branch: str
    commits: List[str]
    diff: str
    changed_files: List[str]
    repo_path: str
    remote: Optional[RemoteInfo] = None


def _run(args: List[str], cwd: str) -> str:
    """Run a git command and return stdout. Raises RuntimeError on failure."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def parse_remote_url(url: str) -> Optional[RemoteInfo]:
    """
    Parse a git remote URL into a RemoteInfo.

    Handles both HTTPS and SSH formats:
      https://github.com/owner/repo.git
      git@github.com:owner/repo.git
    """
    https_re = re.compile(r"https?://([^/]+)/([^/]+)/([^/]+?)(?:\.git)?$")
    ssh_re = re.compile(r"git@([^:]+):([^/]+)/([^/]+?)(?:\.git)?$")

    match = https_re.match(url) or ssh_re.match(url)
    if not match:
        return None

    host, owner, repo = match.group(1), match.group(2), match.group(3)
    platform = Platform.GITHUB if host == "github.com" else Platform.GITEA

    return RemoteInfo(platform=platform, host=host, owner=owner, repo=repo, url=url)


def get_remote_info(repo_path: str) -> Optional[RemoteInfo]:
    try:
        url = _run(["remote", "get-url", "origin"], repo_path)
        return parse_remote_url(url)
    except RuntimeError:
        return None


def get_current_branch(repo_path: str) -> str:
    return _run(["branch", "--show-current"], repo_path)


def get_commits(repo_path: str, base_branch: str) -> List[str]:
    output = _run(
        ["log", f"{base_branch}..HEAD", "--oneline", "--no-merges"],
        repo_path,
    )
    return [line for line in output.splitlines() if line]


def get_diff(repo_path: str, base_branch: str, max_chars: int = 14000) -> str:
    diff = _run(["diff", f"{base_branch}...HEAD", "--no-color"], repo_path)
    if len(diff) > max_chars:
        diff = (
            diff[:max_chars]
            + f"\n\n... [diff truncated — {len(diff) - max_chars} additional chars omitted]"
        )
    return diff


def get_changed_files(repo_path: str, base_branch: str) -> List[str]:
    output = _run(["diff", f"{base_branch}...HEAD", "--name-status"], repo_path)
    return [line for line in output.splitlines() if line]


def collect_git_context(repo_path: str, base_branch: str) -> GitContext:
    """Gather all git context needed to generate a PR description."""
    resolved = str(Path(repo_path).resolve())
    return GitContext(
        current_branch=get_current_branch(resolved),
        base_branch=base_branch,
        commits=get_commits(resolved, base_branch),
        diff=get_diff(resolved, base_branch),
        changed_files=get_changed_files(resolved, base_branch),
        repo_path=resolved,
        remote=get_remote_info(resolved),
    )

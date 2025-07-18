from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _read_git_head(repo_dir: Path) -> str | None:
    """Return the short commit hash from .git/HEAD without git installed."""
    head_file = repo_dir / ".git" / "HEAD"
    if not head_file.is_file():
        return None

    ref = head_file.read_text().strip()
    if ref.startswith("ref:"):
        ref_path = repo_dir / ".git" / ref.split(" ", 1)[1]
        if ref_path.is_file():
            commit = ref_path.read_text().strip()
            return commit[:7]
        return None
    return ref[:7]


def get_version() -> str:
    """Return short git commit hash or a provided VERSION."""
    env_version = os.getenv("GENTLEBOT_VERSION") or os.getenv("VERSION")
    if env_version:
        return env_version

    repo_dir = Path(__file__).parent

    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir
        )
        return out.decode().strip()
    except Exception:
        commit = _read_git_head(repo_dir)
        return commit if commit else "unknown"


VERSION = get_version()


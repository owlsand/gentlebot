from __future__ import annotations
import subprocess
from pathlib import Path


def get_version() -> str:
    """Return short git commit hash or 'unknown'."""
    try:
        repo_dir = Path(__file__).parent
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


VERSION = get_version()

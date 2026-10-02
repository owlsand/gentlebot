"""Exercise the production deploy shell with an isolated Docker substitute."""
import os
from pathlib import Path
import subprocess

import pytest
import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/deploy.yml"
SHA = "a" * 40


@pytest.mark.parametrize("health,actual_image,expected_status", [
    ("healthy", "sha256:new", 0),
    ("none", "sha256:new", 0),
    ("unhealthy", "sha256:new", 1),
    ("starting", "sha256:new", 1),
    ("healthy", "sha256:old", 1),
])
def test_deploy_requires_expected_image_and_health(tmp_path, health, actual_image, expected_status):
    step = yaml.safe_load(WORKFLOW.read_text())["jobs"]["deploy"]["steps"][-1]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text('''#!/bin/bash
set -eu
printf '%s\\n' "$*" >> "$DEPLOY_DIR/commands"
case "$*" in
  'pull '*) exit 0 ;;
  'image inspect '*) echo sha256:new ;;
  'compose up -d --no-deps gentlebot'|'compose ps gentlebot') exit 0 ;;
  'inspect -f {{.State.Status}} gentlebot') echo running ;;
  'inspect -f {{.Image}} gentlebot') echo "$TEST_ACTUAL_IMAGE" ;;
  'inspect -f {{if .State.Health}}'*) echo "$TEST_HEALTH" ;;
  *) exit 20 ;;
esac
''')
    docker.chmod(0o755)
    sleep = bin_dir / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
           "DEPLOY_DIR": str(tmp_path), "DEPLOY_SHA": SHA,
           "TEST_HEALTH": health, "TEST_ACTUAL_IMAGE": actual_image}
    result = subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == expected_status, result.stdout + result.stderr
    commands = (tmp_path / "commands").read_text()
    assert f"pull ghcr.io/owlsand/gentlebot:{SHA}\n" in commands
    assert "compose up -d --no-deps gentlebot\n" in commands
    override = yaml.safe_load((tmp_path / "docker-compose.override.yml").read_text())
    assert override == {"services": {"gentlebot": {"image": f"ghcr.io/owlsand/gentlebot:{SHA}"}}}
    if expected_status:
        assert "did not become healthy on the expected image" in result.stderr

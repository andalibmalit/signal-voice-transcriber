"""Startup validation: Dockerfile security check."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).parent.parent.parent


def test_dockerfile_does_not_run_as_root() -> None:
    """Dockerfile should have a USER directive so the container doesn't run as root."""
    dockerfile = REPO_ROOT / "Dockerfile"
    if not dockerfile.exists():
        pytest.skip("No Dockerfile found")

    content = dockerfile.read_text()
    # Look for a USER directive that sets a non-root user
    user_lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip().upper().startswith("USER ")
    ]
    assert user_lines, "Dockerfile has no USER directive — container would run as root"
    # The last USER directive is what the container runs as
    last_user = user_lines[-1].split(None, 1)[1].strip()
    assert last_user.lower() != "root", f"Dockerfile USER is 'root'"

"""Every package module must import cleanly in a fresh interpreter, in any order."""

import subprocess
import sys

import pytest

MODULES = [
    "hippo.knowledge.generation_profiles",
    "hippo.knowledge.temporal",
    "hippo.ingest.pipeline",
    "hippo.ingest.managed_activation",
    "hippo.ask",
    "hippo.mcp_server",
    "hippo.cli",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_first_in_a_fresh_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]

"""Every package module must import cleanly in a fresh interpreter, in any order."""

import subprocess
import sys

import pytest

# The knowledge entries come first because that is the order the import-order
# incident broke: a knowledge module imported first reached back into ingest,
# whose package `__init__` reached forward again. The two modules
# `test_layering.py` allows to keep importing ingest -- `input_binding` and
# `public_errors` -- are listed here on purpose: that list is only tolerable
# while each of its entries is proved acyclic in every order.
MODULES = [
    "hippo.knowledge.generation_profiles",
    "hippo.knowledge.input_binding",
    "hippo.knowledge.inputs",
    "hippo.knowledge.public_errors",
    "hippo.knowledge.temporal",
    "hippo.ingest",
    "hippo.ingest.pipeline",
    "hippo.ingest.managed_activation",
    "hippo.ingest.prose_generation",
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

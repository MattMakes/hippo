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
    "hippo.ingest.build_run",
    "hippo.ingest.pipeline",
    "hippo.ingest.managed_activation",
    "hippo.ingest.prose_generation",
    "hippo.ask",
    "hippo.mcp_server",
    "hippo.cli",
    "hippo.connectors.loader",
    # The port's one `ingest` -> `connectors` edge (ruling R54): the dispatch imports these two,
    # and they import only leaves, so every order must still load in a fresh interpreter.
    "hippo.connectors.lanes",
    "hippo.connectors.local.connector",
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


# What `hippo --help` must not drag in. Absences, not a count: the CLI grows subcommands,
# and a total would only say that the number changed. Each of these is here for a reason.
#
# `hippo.ingest.pipeline` and `hippo.ingest.managed_activation` are the indexing lanes,
# `hippo.knowledge.public_errors` is the closed failure table, and `fastapi` / `starlette`
# are the server. None of them is needed to print a usage string, and every one of them is
# a package that imports a chain of others -- which is why `cli.py` keeps its own copy of
# the `authorization_changed` literal rather than importing the module that owns it
# (`test_the_three_copies_of_the_denial_code_are_the_same_string`).
HELP_MUST_NOT_IMPORT = (
    "hippo.ingest.pipeline",
    "hippo.ingest.managed_activation",
    "hippo.knowledge.public_errors",
    "fastapi",
    "starlette",
)


def test_hippo_help_imports_no_serving_machinery() -> None:
    """4c re-review N4: `hippo --help` stays cheap, and the constraint is pinned not remembered."""
    program = (
        "import sys;"
        "from hippo.cli import main;"
        "sys.argv = ['hippo', '--help'];"
        "code = 0\n"
        "try:\n"
        "    main(['--help'])\n"
        "except SystemExit as exit:\n"
        "    code = exit.code or 0\n"
        "print('EXIT', code)\n"
        "print('\\n'.join(sorted(sys.modules)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr[-2000:]
    loaded = set(result.stdout.splitlines())
    assert "EXIT 0" in loaded
    assert not loaded & set(HELP_MUST_NOT_IMPORT), sorted(loaded & set(HELP_MUST_NOT_IMPORT))

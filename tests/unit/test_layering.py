"""`hippo.ingest` may import `hippo.knowledge`; never the reverse.

The import-order incident that motivated this guard is recorded in
`ai_docs/checkpoints/2026-09-11-execution-state.md`: knowledge modules reached
back into ingest for the accepted-input contracts, ingest's package `__init__`
pulled the whole pipeline, and the two met in a cycle that only showed up when a
knowledge module happened to be imported first. `test_import_order.py` proves
each entry module still imports in a fresh interpreter; this module pins the
shape that makes that true, so the next reverse import fails here with a reason
rather than there with an `ImportError` in one arbitrary order.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

import hippo.knowledge

KNOWLEDGE = Path(hippo.knowledge.__file__).parent

# `from ..ingest...`, `from hippo.ingest...`, `import hippo.ingest...` and the two
# package-object spellings, at any relative depth, anywhere in the file -- a
# deferred import inside a function is still a knowledge module depending on ingest.
REVERSE_IMPORT = re.compile(
    r"^[ \t]*(?:from[ \t]+(?:\.{2,}ingest|hippo\.ingest)\b"
    r"|from[ \t]+(?:\.{2,}|hippo)[ \t]+import[ \t]+ingest\b"
    r"|import[ \t]+hippo\.ingest\b)",
    re.MULTILINE,
)

# Every entry is a module that cannot be moved without moving ingest itself, and
# every entry is proved acyclic by its own case in `test_import_order.py`. Shrink
# this, never grow it: a new reverse import belongs in `hippo.knowledge.inputs`
# or above the layer boundary, not here.
ALLOWED = {
    "input_binding.py": (
        "PreparedChunk carries ingest's provenance value types, which subclass "
        "ingest.readers.ReadError and render an ingest.readers.Document"
    ),
    "public_errors.py": (
        "the closed exception table is keyed by the ingest classes themselves, "
        "so it cannot be built without importing them"
    ),
}


def _run(source: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True, timeout=120, check=False
    )


def test_knowledge_modules_do_not_import_ingest() -> None:
    offenders = {
        path.name: [line for line in path.read_text().splitlines() if REVERSE_IMPORT.match(line)]
        for path in sorted(KNOWLEDGE.rglob("*.py"))
        if REVERSE_IMPORT.search(path.read_text())
    }
    assert set(offenders) == set(ALLOWED), (
        f"knowledge -> ingest imports changed: {offenders}\n"
        f"allowed only for {ALLOWED}; move shared contracts into hippo.knowledge.inputs instead"
    )


def _ingest_modules(module: str) -> list[str]:
    result = _run(
        f"import sys, {module}\n"
        "print('\\n'.join(sorted(n for n in sys.modules if n.startswith('hippo.ingest'))))\n"
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout.split()


def test_the_accepted_input_contracts_reach_no_ingest_module() -> None:
    """The new leaf is the layer boundary itself; it loads no ingest module at all."""
    assert _ingest_modules("hippo.knowledge.inputs") == []


def test_generation_profiles_no_longer_drags_in_the_capture_or_build_lane() -> None:
    """The incident's entry module still reaches ingest, through the one allowed import.

    `input_binding` pulls `prepared_chunks` and the readers it maps, which is the
    residual the allowlist names. The absences are the contract: the capture side,
    the pipeline and the managed lane are what closed the cycle, and none of them
    is reachable from a knowledge module any more.
    """
    loaded = _ingest_modules("hippo.knowledge.generation_profiles")
    assert "hippo.ingest.prepared_chunks" in loaded, loaded
    assert not {
        "hippo.ingest.accepted_inputs",
        "hippo.ingest.chunker",
        "hippo.ingest.managed_activation",
        "hippo.ingest.pipeline",
        "hippo.ingest.prose_generation",
        "hippo.ingest.repos",
    }.intersection(loaded), loaded


def test_importing_the_ingest_package_does_not_load_the_pipeline() -> None:
    """`import hippo.ingest` is cheap; the public names still resolve on demand."""
    result = _run(
        "import sys\n"
        "import hippo.ingest\n"
        "print('hippo.ingest.pipeline' in sys.modules)\n"
        "print(hippo.ingest.add_text.__module__)\n"
        "print('hippo.ingest.pipeline' in sys.modules)\n"
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.split() == ["False", "hippo.ingest.pipeline", "True"], result.stdout


def test_an_unknown_ingest_attribute_is_an_attribute_error() -> None:
    result = _run("import hippo.ingest; hippo.ingest.no_such_name")
    assert result.returncode != 0
    assert "AttributeError" in result.stderr, result.stderr[-2000:]


def test_the_pipeline_imports_the_managed_lane_eagerly() -> None:
    """The lazy `pipeline._managed()` accessor existed only for the cycle."""
    import hippo.ingest.pipeline as pipeline

    assert not hasattr(pipeline, "_managed")
    result = _run(
        "import sys, hippo.ingest.pipeline; print('hippo.ingest.managed_activation' in sys.modules)"
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "True", result.stdout


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("hippo.ingest.accepted_inputs", "AcceptedInputs"),
        ("hippo.ingest.accepted_inputs", "ByteInput"),
        ("hippo.ingest.accepted_inputs", "CaptureLimits"),
        ("hippo.ingest.accepted_inputs", "CaptureTooLarge"),
        ("hippo.ingest.accepted_inputs", "ExcludedInput"),
        ("hippo.ingest.accepted_inputs", "FileInput"),
        ("hippo.ingest.accepted_inputs", "InputCaptureError"),
        ("hippo.ingest.accepted_inputs", "InputDisposition"),
        ("hippo.ingest.accepted_inputs", "UnsupportedCaptureInput"),
        ("hippo.ingest.provenance", "RawInput"),
        ("hippo.knowledge.generation_profiles", "MANIFEST_EXTERNAL_ID"),
    ],
)
def test_the_moved_contracts_keep_their_existing_import_paths(module: str, name: str) -> None:
    """One class, reachable under both names: no caller changes its imports."""
    import importlib

    import hippo.knowledge.inputs as inputs

    assert getattr(importlib.import_module(module), name) is getattr(inputs, name)

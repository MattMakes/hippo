# Evidence: layering follow-up — `hippo.knowledge` must not import `hippo.ingest`

Branch `wp/layering`, worktree `.worktrees/layering`. Base `rag-it-all-tibs` `65fbcab` (the HEAD
named in the spawn message, not the `26f9a55` in the rulebook). No merges.
Python `.venv/bin/python` 3.12.11, pytest 9.1.1, Ruff 0.16.6, `mcp` pinned to 2.1.1 per the rulebook.

Commits:

| Hash | Subject |
|---|---|
| `1dab194` | Move the accepted-input contracts into hippo.knowledge |
| `895f198` | Import the ingest package lazily and the managed lane eagerly |
| *(this file)* | Record the layering evidence — hash reported in the `horch done` summary |

Files created: `src/hippo/knowledge/inputs.py`, `tests/unit/test_layering.py`, this file.
Files modified: `src/hippo/ingest/accepted_inputs.py`, `src/hippo/ingest/provenance.py`,
`src/hippo/ingest/__init__.py`, `src/hippo/ingest/pipeline.py`,
`src/hippo/knowledge/generation_profiles.py`, `src/hippo/knowledge/input_binding.py`,
`tests/unit/test_import_order.py`.

Not touched: `src/hippo/ingest/prose_generation.py` (the brief allowed its import lines; the
re-exports made every one of them still correct, so changing them would have been churn — see
decision 1), `src/hippo/knowledge/public_errors.py` and every other file.

---

## Decision 1 — the accepted-input contracts move down, the capture stays up

`hippo.knowledge.generation_profiles` validates a generation's accepted manifest and
`hippo.knowledge.input_binding` materializes an accepted binding, so both need the accepted-input
*values*. Neither needs the code that opens a file or streams bytes into the raw store. The values
now live in the new leaf `src/hippo/knowledge/inputs.py`, which imports only
`hippo.knowledge.identity` and `hippo.knowledge.raw_artifacts`:

`MANIFEST_EXTERNAL_ID`, `ByteInput`, `FileInput`, `ExcludedInput`, `CaptureLimits`,
`InputDisposition`, `RawInput`, `AcceptedInputs`, `InputCaptureError`, `CaptureTooLarge`,
`UnsupportedCaptureInput`, and the helpers those need (`_text`, `_descriptor`, `_input_key`,
`_manifest_bytes`).

`InputCaptureError`, `CaptureTooLarge` and `UnsupportedCaptureInput` were not in the brief's list
but had to come: `AcceptedInputs.__post_init__` raises `CaptureTooLarge` on its own limit checks, so
the inventory cannot validate itself without them. `CaptureCancelled` is a *build* outcome rather
than an input contract and stayed in `hippo.ingest.accepted_inputs` with `_checkpoint`, `_open_file`,
`_CaptureReader`, `_capture_one` and `capture_raw_inputs`.

`hippo.ingest.accepted_inputs` re-exports all of them (with an explicit `__all__` recording that the
imports are the compatibility surface, so nobody deletes them as unused) and
`hippo.ingest.provenance` re-exports `RawInput`. `hippo.knowledge.generation_profiles` re-exports
`MANIFEST_EXTERNAL_ID`. **Each name is the same object under both paths**, so `isinstance`, `except`
and `type(x) is C` all keep working across the boundary, and no caller and no test changed an import
for this reason — which is why `prose_generation.py`, listed in the brief as mine for its import
lines, needed no edit at all. `test_layering.py::test_the_moved_contracts_keep_their_existing_import_paths`
pins the identity for all eleven names.

## Decision 2 — `hippo/ingest/__init__.py` binds its names on first use

The file bound seventeen public names by importing `pipeline`, `chunker`, `readers` and `repos` at
module level. Importing *any* module in the package runs the package `__init__` first, so
`import hippo.ingest.accepted_inputs` pulled the pipeline, the code graph, the indexer and (before
`da51784`) the managed lane. That is the half of the cycle the lazy accessor was working around.

A module-level `__getattr__` (PEP 562) over a `name -> submodule` table replaces the eager imports;
`__all__` and `__dir__` derive from the same table. `from hippo.ingest import add_text` and
`hippo.ingest.add_text` both still work, `from hippo.ingest import pipeline` is unaffected (the
import system resolves submodules itself), and an unknown attribute raises `AttributeError` rather
than falling through to an import error — pinned by
`test_an_unknown_ingest_attribute_is_an_attribute_error`.

## Decision 3 — `pipeline._managed()` is gone

`pipeline.py` imports `managed_activation` at module level again (`from . import
managed_activation, readers, repos`) and its seventeen `_managed().x` call sites are
`managed_activation.x`. Nothing else in that file changed.
`test_the_pipeline_imports_the_managed_lane_eagerly` asserts both halves: the accessor no longer
exists, and a fresh interpreter that imports `hippo.ingest.pipeline` has
`hippo.ingest.managed_activation` in `sys.modules`.

**The RED was produced by removing the accessor first**, which is the honest order: with
decisions 1 and 2 already in place the removal is a no-op, so it proves nothing. Removing
`_managed()` against the otherwise-unchanged base restored the original `ImportError`:

```
File ".../hippo/ingest/prose_generation.py", line 25, in <module>
    from ..knowledge.generation_profiles import MANIFEST_EXTERNAL_ID, embedding_mode, ...
ImportError: cannot import name 'MANIFEST_EXTERNAL_ID' from partially initialized module
'hippo.knowledge.generation_profiles' (most likely due to a circular import)
```

## Decision 4 — the guard, with two allowlisted residuals

`tests/unit/test_layering.py::test_knowledge_modules_do_not_import_ingest` greps every
`src/hippo/knowledge/**/*.py` for `from ..ingest`, `from hippo.ingest`, `import hippo.ingest`,
`from .. import ingest` and `from hippo import ingest`, anywhere in the file (a deferred import
inside a function is still a dependency), and asserts the offending files are **exactly** the
allowlist — so an entry that stops being needed must be deleted, not left to rot.

Two entries survive, and the orchestrator ruled (in writing, in answer to the BLOCKED question
below) that they are allowlisted with a reason each rather than chased outside this brief's files:

1. **`input_binding.py` -> `ingest.prepared_chunks.PreparedChunk`.** `PreparedChunk` carries
   ingest's provenance value types (`OriginalUnit`, `OriginalSegment`, `GeneratedSegment`,
   `OriginalLines`, `ProvenanceDocument`), and those are bound to the readers, not just to the
   package: `UnsupportedProvenanceFormat` and `UnsupportedChunkProvenance` subclass
   `ingest.readers.ReadError`, and `ProvenanceDocument.to_document()` returns an
   `ingest.readers.Document`. Moving them means moving the readers, which is a different slice.
2. **`public_errors.py` -> `ingest.accepted_inputs`, `ingest.prose_generation`, `ingest.readers`.**
   `_ROWS` is a closed table keyed by the exception *classes*, so it cannot be built without
   importing them, and a deferred import would change when the table exists. The file is on this
   brief's do-NOT-touch list and belongs to another owner.

**Both are one-directional and neither is a cycle**, which is what makes the allowlist tolerable
rather than a hole. That is not asserted by assumption: both modules are now cases in
`tests/unit/test_import_order.py`, so each is proved to import first in a fresh interpreter, in
addition to `hippo.knowledge.inputs`, `hippo.ingest` and `hippo.ingest.prose_generation`.

`test_generation_profiles_no_longer_drags_in_the_capture_or_build_lane` states the residual
positively: importing `hippo.knowledge.generation_profiles` does reach
`hippo.ingest.prepared_chunks` (through the allowlisted import), and does **not** reach
`accepted_inputs`, `chunker`, `repos`, `pipeline`, `managed_activation` or `prose_generation`.
`test_the_accepted_input_contracts_reach_no_ingest_module` pins the stronger claim for the new leaf:
importing `hippo.knowledge.inputs` loads no `hippo.ingest*` module at all.

**Follow-up (residual, not closed here):** the brief's GOAL — `hippo.knowledge` imports *nothing*
from `hippo.ingest` — is reached for everything except those two entries. Closing them needs a
separate slice that either moves the provenance/prepared-chunk value layer (and the reader
exceptions it subclasses) below the boundary, or moves `public_errors` above it. The guard's
allowlist is the place that will notice.

---

## Runs

All Fake. Ladybug was not run: this slice moves class definitions between modules and changes no
behavior, no query, no write and no stored shape, so no store backend can distinguish before from
after. Ladybug/Neo4j is not required, and the disposable container was never requested or used.

Command form (a) was not needed and form (b) was used only for the whole-suite sweep, whose
collection includes module-level `fastapi.testclient` importers:
`-W error -W "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning"`.
The four targeted runs below carry a bare `-W error`; none of their modules imports
`fastapi.testclient`.

| # | What | Command | Result | Log |
|---|---|---|---|---|
| 1 | Baseline, before any edit | brief's set, `-q -o addopts='' -W error` | 328 passed, 3 skipped | `/tmp/hippo-layering-baseline.log` |
| 2 | RED | `test_import_order.py test_layering.py` | **19 failed**, 9 passed | `/tmp/hippo-layering-red.log` |
| 3 | GREEN | brief's set + `test_layering.py` + `test_managed_prose_preparation.py` + `test_staged_prose_writer.py` | 403 passed, 3 skipped | `/tmp/hippo-layering-green.log` |
| 4 | Whole `tests/unit` sweep | `tests/unit -q -o addopts='' -W error -W "ignore:..."` | 3850 passed, 28 skipped, **1 failed (pre-existing, not mine)** | `/tmp/hippo-layering-sweep.log` |

Run 1 and run 3's file set: `test_import_order.py`, `test_accepted_inputs.py`,
`test_managed_input_binding.py` (the brief's `test_input_binding.py` does not exist),
`test_generation_profiles.py`, `test_prose_generation.py`, `test_managed_pipeline_activation.py`,
`test_ingest_pipeline.py`, plus `test_managed_prose_preparation.py` and `test_staged_prose_writer.py`
in run 3.

Run 2's failures are the intended ones: five `test_import_order` cases
(`hippo.knowledge.generation_profiles`, `hippo.knowledge.input_binding`, `hippo.knowledge.inputs`,
`hippo.ask`, `hippo.mcp_server` — every one of them a knowledge-first import hitting the restored
cycle), the layering guard, the contracts-reach-no-ingest check, the lazy-package check, and the
eleven moved-path identity cases.

### The one sweep failure is pre-existing and already fixed upstream

`tests/unit/test_managed_web_surfaces.py::test_an_incoherent_selection_reaches_an_mcp_code_tool_as_a_mapped_failure`
fails at base `65fbcab` as well. Verified by checking `65fbcab` out in this worktree and running
that file alone — 1 failed, 76 passed, `/tmp/hippo-layering-base-websurfaces.log` — then returning to
`wp/layering`. `blast_radius_tool` wraps its body in `mcp_server._answering()`, so it raises
`ToolError("operation_failed: ...")` where the test expects the `ProjectionError` itself. Reported to
the orchestrator, who confirmed it was fixed on `rag-it-all-tibs` at `dfd13b0` (the test now expects
the mapped `ToolError`), after the `65fbcab` this branch is based on. No action here; nothing in this
slice touches `mcp_server.py` or that test.

### The `hippo --help` import footprint still holds

Fresh interpreter, `hippo.cli.main(["--help"])` under `SystemExit`, then `sys.modules`
(`/tmp/hippo-layering-probe.py`, output in `/tmp/hippo-layering-help-footprint.log`):

```
hippo.* modules imported: 34     total sys.modules: 488
  absent   hippo.ingest.pipeline
  absent   hippo.ingest.managed_activation
  absent   hippo.ingest.prose_generation
  absent   hippo.knowledge.public_errors
  absent   fastapi
  absent   starlette
  ingest modules loaded: []
```

No `hippo.ingest` module is loaded at all, and `hippo.knowledge.inputs` is not in the graph either;
the 34 `hippo.*` modules are the same set the `pa4c` re-review measured, whose counts it already
recorded as environment-dependent and not a contract. The absences are the contract and they hold.

### Ruff

`.venv/bin/ruff check src/hippo tests/unit/test_layering.py tests/unit/test_import_order.py` and
`ruff format --check` over the same paths: clean, "124 files already formatted". This file was
checked with `ruff format --check` too, per the rulebook's note about the CI Markdown job.

---

## The BLOCKED question and its answer

Asked before writing any code, because decision 4 as written could not pass inside the brief's FILES
list: after decisions 1–3 the two residuals above remain, `public_errors.py` is do-NOT-touch, and
moving `PreparedChunk` is far more than the "imports only" the brief allows for `input_binding.py`.
The orchestrator's ruling, verbatim in substance: allowlist both, with a path and a one-line reason
each, prove them non-cyclic with the import-order test, record the residual as a follow-up here, do
not expand the file list, and keep "`_managed()` removed + every order clean" as the DONE criteria.
That is what is implemented above.

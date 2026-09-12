# CC5 evidence: mapped code chunks (gate CD4)

Worker `backend-developer-15`, 2026-09-12. Branch `wp/cc5`, worktree `.worktrees/cc5`, base
`91131e7` (the merge of `wp/cc4`). Contract:
`ai_docs/plans/rag-it-all-task-5-managed-code-capture.md` sections 4 and 6 and ruling 10; brief
`ai_docs/handoffs/briefs/cc5-code-chunks.md`; CC4's evidence `evidence-cc4.md`. No gate checkbox is
set here.

## Files

Created, and nothing else was touched:

- `src/hippo/ingest/prepared_code_chunks.py`
- `tests/unit/test_prepared_code_chunks.py`
- this file

## Public signature

```python
CODE_CHUNK_RULE_VERSION = "code-chunks-v1"
CODE_CHUNK_KINDS = ("header", "symbol", "data_object", "window", "prose", "commit")
CODE_REFUSAL_REASONS = ("binary", "empty")
CODE_PLACEHOLDER_RULE = "code-placeholder-v1"
CODE_LINE_JOIN_RULE = "code-line-join-v1"
CODE_COMMIT_RULE = "code-commit-v1"


def prepare_code_chunks(
    units: Iterable[CapturedCode],
    *,
    facts: CodeGraph | None,
    settings: CodeChunkSettings,
    max_chunks: int,
) -> PreparedCodeChunks: ...
```

Values, all frozen: `CapturedCode(raw_input, provenance)`, `CodeChunkSettings(size_chars,
overlap_chars)` with `effective_size` / `effective_overlap` / `profile`, `CodeChunkRefusal(input_key,
logical_path, reason)`, `CommitSegment(text, rule_id, commit_id)`, `PreparedCodeChunk`,
`PreparedCodeChunks(rule_version, chunker_profile, chunks, refusals)`. Errors:
`UnsupportedCodeChunkInput`, `CodeChunkParityError` (both `ReadError`) and `TooManyCodeChunks`
(`TooLarge`).

`PreparedCodeChunk` carries `ordinal, kind, title, text, defines, extract_text, logical_path,
symbol_id, data_object_ids, commit_id, commit_sha, original_units, retrieval_segments,
segment_dependencies, title_dependencies, original_dependencies, originals, placeholders,
chunker_profile, rule_version`, a derived `chunk_key`, and the `requires_view` / `to_chunk`
properties `PreparedChunk` already has, so CC6 can treat a prose chunk and a code chunk the same way.

## Three deviations from the brief's spelling, each forced

1. **`units` is `Iterable[CapturedCode]`, not `Iterable[CodeUnit]`.** Requirement 3 asks for an
   explicit refusal for a binary or empty file, and CC4 gives those outcomes **no `CodeUnit` at
   all** (`CodeProvenance.unit is None`) and no identity either: `ProvenanceRead` carries no
   `input_key` and a binary read carries no `original_units`. A refusal that cannot name the file it
   refused is not an explicit reason, so the element type is the accepted input paired with its
   provenance. CC9 holds both in the same loop where it calls `read_code_provenance`.
2. **`max_chunks` is a required keyword.** Plan section 8.3 makes the passage ceiling an operational
   limit outside generation identity, so it must not sit on `CodeChunkSettings`, which is the
   identity-bearing group. It is an argument rather than an import of `pipeline.MAX_CHUNKS` because
   `ingest.pipeline` will import this lane through CC9/CC10 and the reverse import would close a
   cycle. A source past the ceiling raises `TooManyCodeChunks` rather than recording a refusal,
   because section 8.3 says a ceiling refuses the build and never truncates.
3. **Two chunk kinds beyond the four the brief names.** `window` is a line window of a code file
   with no symbol tree (every config file, an unwalked language, a parsed file whose module symbol is
   missing); `prose` is a file the committed `chunk_document` sends down its **prose** branch. That
   branch is reachable in this lane: CC4 accepts extensionless known-text names (`README`,
   `Makefile`, `LICENSE`) and `go.mod`, none of which is in `readers.CODE_EXTENSIONS`, so
   `doc.is_code` is False and `_chunk_prose` runs. Those files are delegated to the reviewed
   `prepare_prose_chunks` and renumbered, so the prose mapping is not re-derived here.

`facts: CodeGraph` keeps the brief's spelling.

## How parity is achieved, and what the parity test therefore proves

Plan section 6 step 6 says this seam **wraps** `chunk_documents(..., code=code)`. It does, in two
ways:

- Every boundary decision is the committed chunker's own: `_file_module`, `_members`,
  `_placeholders`, `_placeholder`, `_line_numbers`, `_split_rows`, `_title_range`, `_text_of`,
  `_mention_index`, `_data_ids_in`, `code_windows`, `_chunk_commits` and `MIN_OPENIE_DOC_CHARS` are
  called, not copied. The only re-expressed function is `_header_rows`, because the committed one
  returns `(line, text)` and discards which member each placeholder stands for;
  `test_the_reexpressed_header_rows_equal_the_committed_ones` pins the two equal row for row.
- `prepare_code_chunks` then runs the committed `chunk_documents` over the same documents and
  refuses to return unless its own `Chunk` list is equal field for field
  (`CodeChunkParityError`). Byte-identity is an invariant of the module, not only a test result.

**Read the 2,000-case parity test as a divergence guard, not as an independent-chunker proof.**
Because the latch runs on every call, `test_two_thousand_seeded_units_match_the_committed_chunker`
cannot fail on text alone without the latch firing first; what it adds is that the latch never fires
across 2,200 seeded files in 50 sources, that every passage still reconstructs exactly from its own
segments, and that all six kinds and all three generated rules are actually reached.
`test_a_disagreement_with_the_committed_chunker_fails_closed` monkeypatches a perturbed
`chunk_documents` and proves the latch is not vacuous.

## What is generated, and what it depends on

| Rendering | Rule | Original dependency |
| --- | --- | --- |
| A container header's placeholder line for a member | `code-placeholder-v1` | the member's first nonempty analysis line |
| The `"\n"` the chunker joins two rows with, when it is not the file's own character | `code-line-join-v1` | the last character of the line before and the first of the line after |
| A whole commit passage | `code-commit-v1` | none: a `CommitSegment` naming the commit record CC7 binds |

A newline between two consecutive real lines whose file terminator is exactly `"\n"` **is** the
file's own character, so it merges into the original region around it. That is why an LF file's
symbol body is one `OriginalSegment` and a CRLF file's is not: the chunker writes `"\n"` where the
file holds `"\r\n"`, so every join in a CRLF file is honestly generated. Dependencies are minimal
(edge characters), following `prepared_chunks._MappedText.join`; the alternative — a placeholder
depending on its member's whole range — would inflate a module header's closure to the whole file.

Coverage of the chunk text is a partition: `test_two_thousand_seeded_units_match_the_committed_chunker`
asserts that the segment lengths sum to `len(chunk.text)` for every passage, and
`PreparedCodeChunk.__post_init__` refuses any chunk whose segments do not reconstruct its text.
Note the direction: the partition is over the **passage**, not over the file. A CRLF file's `"\r"`
characters and every line a placeholder replaced are outside the passage by construction, which is
the legacy chunker's behaviour and is recorded rather than repaired.

## Results

All runs from `.worktrees/cc5` with `.venv/bin/python` (3.12.11, `mcp==2.1.1` pinned). Pure
preparation: no store, no model, no clock, so **no Ladybug or Neo4j run is applicable to CD4** and
none was made.

| Run | Command | Result | Log |
| --- | --- | --- | --- |
| Baseline before RED | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_ingest_chunker.py tests/unit/test_managed_chunk_provenance.py tests/unit/test_code_provenance.py -q -o addopts='' -W error` | 163 passed | `/tmp/hippo-cc5-baseline.log` |
| RED | the new test file | 1 failed, 30 errors, `ModuleNotFoundError: No module named 'hippo.ingest.prepared_code_chunks'` | `/tmp/hippo-cc5-red.log` |
| GREEN, CD4 command | `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_prepared_code_chunks.py tests/unit/test_ingest_chunker.py -q -o addopts='' -W error` | **93 passed** | `/tmp/hippo-cc5-cd4.log` |
| GREEN, downstream | the CD4 files plus `test_managed_chunk_provenance.py test_code_provenance.py test_repo_capture.py test_ingest_readers.py test_layering.py test_managed_reader_provenance.py` | 337 passed | `/tmp/hippo-cc5-green.log` |
| GREEN, consumers | `tests/unit/test_ingest_pipeline.py tests/unit/test_codegraph.py` | 122 passed | `/tmp/hippo-cc5-pipeline.log` |
| Seeded parity alone | `tests/unit/test_prepared_code_chunks.py::test_two_thousand_seeded_units_match_the_committed_chunker` | 1 passed; 2,200 seeded files in 50 sources yield 2,118 units, the other 82 being the binary and empty refusals the generator also produces | `/tmp/hippo-cc5-seeded.log` |

Per file: `test_prepared_code_chunks.py` 32 passed.

The CD4 CHECK line as the ledger spells it runs from `/Users/mascott/projects/hippo`; the command
above is byte-identical but was run from `.worktrees/cc5`, so the gate checker's own run passes only
once `wp/cc5` lands on `rag-it-all-tibs`.

No `filterwarnings` marker and no command-line warning filter were needed: the new test module does
not import `fastapi.testclient`, so the sanctioned anyio exception does not arise. Plain `-W error`
throughout, and tree-sitter parses cleanly under it.

Ruff, over both files changed and over this document:

```
.venv/bin/ruff check src/hippo/ingest/prepared_code_chunks.py tests/unit/test_prepared_code_chunks.py
.venv/bin/ruff format --check <the same two files> <this file>
```

`All checks passed!` and `already formatted`.

## How each CD4 criterion is covered

| CD4 criterion | Test |
| --- | --- |
| prepared chunk text, order and `defines` equal `chunk_documents(..., code=code)` | `test_symbol_and_header_passages_match_the_committed_chunker`, `test_two_thousand_seeded_units_match_the_committed_chunker`, and the in-module latch on every call |
| exact original line ranges plus explicitly marked generated segments | `test_every_chunk_reconstructs_from_its_own_segments`, `test_originals_close_over_every_declared_dependency`, `test_a_carriage_return_file_marks_each_line_join_as_generated` |
| the context header | `test_a_header_places_one_generated_placeholder_per_member`, `test_every_placeholder_depends_on_lines_inside_the_member_it_stands_for` |
| data-object mention passages | `test_a_sql_file_keeps_line_windows_and_names_the_objects_they_declare` — see finding 1: the committed chunker synthesizes no mention *text* |
| commit passages | `test_a_commit_passage_is_generated_from_its_commit_record_alone`, `test_commit_passages_come_last_and_keep_the_ordinal_run`, `test_a_commit_that_touched_many_symbols_says_what_was_cut` |
| oversized bodies split at statement boundaries as today | `test_an_oversized_body_splits_at_statement_boundaries_as_today` |
| a chunk byte-identical to one original region carries no generated segment | `test_a_pure_line_feed_body_is_one_original_region_with_nothing_generated`, `test_a_passage_that_is_exactly_its_source_lines_needs_no_view` |
| remapped, rich and already-derived inputs reject | `test_a_remapped_unit_is_explicitly_unsupported`, `test_an_input_that_is_not_captured_code_is_rejected`, `test_two_inputs_claiming_one_logical_path_are_rejected` |
| refusals with an explicit reason, nothing truncated silently | `test_a_binary_or_empty_input_produces_no_chunk_and_an_explicit_reason`, `test_a_refused_input_keeps_its_accepted_input_key`, `test_passing_the_chunk_ceiling_refuses_rather_than_truncating` |
| rule version pinned, fixture digest pinned against it (ruling 10 / review M2) | `test_the_rule_version_is_frozen_and_travels_with_every_result`, `test_the_parity_fixture_digest_is_pinned_against_the_rule_version` |
| pure: no store, model or clock | `test_the_module_holds_no_store_model_or_clock`, and `test_layering.py` stays green |

## Statements a reviewer should read as claims, not proofs

1. **The pinned fixture digest is deliberately brittle.** It covers chunk kinds, titles, texts,
   `defines`, `extract_text`, segment descriptors and original closures over a seeded corpus that
   runs the real tree-sitter walkers. A grammar upgrade, a walker change or a chunker change all
   break it. That is ruling 10's point — a changed derivation must not be silently resumable — but it
   means the remedy for a legitimate upstream change is *bump `CODE_CHUNK_RULE_VERSION` and
   re-pin*, not "update the constant".
2. **`requires_view` is almost always True for code**, because `_original_closure` expands to
   complete source lines and therefore keeps the newline the passage text dropped. That is the same
   behaviour `prepare_chunks` already has for prose, and it is conservative in the safe direction
   (CC6 builds a view it may not strictly need, never omits one it does).
   `test_a_passage_that_is_exactly_its_source_lines_needs_no_view` shows the one shape where it is
   False: a file with no trailing newline whose last symbol is the whole passage.
3. **The seeded corpus mixes exotic line boundaries on purpose.** One file in seven has a form feed
   or a lone `\r` spliced in, because `str.splitlines` — which the legacy chunker and this module
   both use — treats those as line boundaries while `provenance._lines` does not. Parity holds
   because both sides read the same `splitlines` list; the locators stay honest because they are
   derived from `_lines`. Worth a reviewer's attention rather than a change.

## Findings for the reviewer and for CC6/CC7/CC9

1. **There is no data-object "mention passage" to map.** The brief anticipates "data-object mention
   passages" with their own generated wording. The committed chunker synthesizes none: a data object
   is reached through a passage's `defines` (`chunker._data_ids_in`), both for a `.sql` line window
   and for any symbol passage whose lines name it. `PreparedCodeChunk.data_object_ids` carries that
   set so CC6 can write `DEFINED_IN` without re-deriving it, and `kind="data_object"` names the
   `.sql` **branch**, so a `.sql` window whose lines mention nothing still carries that kind.
2. **`extract_text` is carried for parity but is not mapped to originals.** `title_dependencies` and
   `extraction_segments` are empty for every code kind. A symbol passage's `extract_text` is
   `symbol.doc`, the walker's cleaned docstring, which is not a verbatim slice of any line range.
   Plan section 4 says code files record `openie: "skipped"` and produce no `ProseExtraction`, so
   nothing in the managed lane needs that mapping — but it is a live legacy/managed difference: the
   legacy lane *does* extract docstrings. CC9 owns the `coverage_json` wording.
3. **A `prose`-kind chunk carries `extract_text=None`, so the legacy lane would run OpenIE on it.**
   An extensionless `README` inside a repository is not `readers.PROSE_EXTENSIONS`, so ruling 5
   ("files matching `PROSE_EXTENSIONS` go through OpenIE") does not decide it, and plan section 4's
   "every code, config and unparsed file records `openie: skipped`" does. CC9 needs a ruling on
   whether a `prose`-kind code chunk is extracted or skipped; this seam records the kind and takes no
   position.
4. **Code passage titles are fully synthesized and are not bound to originals.** A title is
   `f"{path} :: {display} (lines a-b)"` or `f"{path} (lines a-b)"` or `f"commit {sha[:10]}: ..."` —
   metadata, never quoted file text — so `title_dependencies` is empty by construction, unlike the
   prose lane where a markdown heading is original text. Only the delegated `prose` kind carries
   title dependencies.
5. **A commit passage can legitimately be empty.** `_commit_text` returns the message unchanged when
   the commit touched no symbol, and a commit with an empty message and no touched symbol renders to
   `""`. `PreparedCodeChunk` allows an empty text for `kind="commit"` only, and emits no
   `CommitSegment` in that case. CC6 must not assume every passage has nonempty dense text;
   `generation_checksums:719-724` already requires dense coverage only for nonempty exact text.
6. **`_commit_text`'s last-resort branch is a hard character cut.** When not even one symbol name
   fits, the committed chunker returns `f"{header}… ({n} symbols)"[:size]`, which can slice a
   commit message mid-character-sequence. It is reproduced as written. It is honest here only
   because the whole commit passage is one generated segment with no original to contradict — but
   CC7 should know the passage text is not a faithful prefix of the commit message.
7. **`CommitSegment` is a third segment type, beside `OriginalSegment` and `GeneratedSegment`.**
   `provenance.GeneratedSegment` requires at least one `original_unit_keys` entry, and a commit
   passage has no captured file behind it at all. `CodeSegment = Segment | CommitSegment`, and
   `segment_descriptors()` renders all three for identity and for CC6's `DerivedRecord`. CC6 must
   bind a `CommitSegment` to CC7's `history_event` `ArtifactRevision`, not to an `EvidenceSpan`.
8. **The passage ceiling is checked after chunking, not before capture.** Plan section 8.3 says a
   ceiling "refuses the build before capture", but the passage count is only knowable once the
   passages exist. CC9 should treat `TooManyCodeChunks` as a pre-inference refusal: it is raised
   before any embedding and before any write, which is what the section's intent (never install a
   partial generation) requires.
9. **Ordinals are assigned inside this seam and are part of `chunk_key`.** Two captures whose file
   *order* differs produce different `chunk_key`s even for identical file content, exactly as the
   legacy `Chunk.ordinal` differs. CC4's inventory is sorted and order-independent, so CC9 must feed
   `units` in that canonical order; this seam preserves the order it is given and does not re-sort.
10. **`prepare_code_chunks` returns an empty result rather than raising when every input refuses.**
    The legacy `pipeline.py:397` raises `ReadError("no readable text was found in this source")` for
    an empty chunk list. That is a source-level decision with user-facing wording, so it is left to
    CC9 rather than duplicated here.
11. **Chunking now runs twice per build.** The latch calls the committed `chunk_documents` in
    addition to the mapped walk. Both are pure string work with no model and no I/O, and the parse
    and embedding passes dominate a repository build by orders of magnitude, but CC9 should know the
    cost is there rather than discover it. Removing the latch would make byte-identity a test
    result again; that trade is the orchestrator's to make, not this slice's.
12. **The brief names `tests/unit/test_prepared_chunks.py` as a baseline suite; no such file
    exists.** The reviewed prose parity suite is `tests/unit/test_managed_chunk_provenance.py`, and
    that is what the baseline run above used.

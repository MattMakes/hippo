# S3 — Apply the V2 review, with the orchestrator's rulings on the contested items (worker: opus-3)

Apply `docs/plans/hippo-for-code/research/V2-decision-review.md` (7 blockers, 17 fixes, 10 nits, plus its
"S2 conflicts" section) to `PLAN.md`. Fix each finding or record why not in the "Review responses" appendix.
The rulings below are binding where V2 offered a choice or where V2 reverses an S2 item; for everything
else follow V2's recommendation. Cite research ids as before.

## Rulings

**Ruling 1 — the `used_code_seeds` gate (V2 blocker on dense seeds).** Both of V2's options, together:
(a) `used_code_seeds = any lexical anchor seed kept` (identifiers, stack frames, fenced code, diff hunks).
Dense seeds add reset mass but never flip the gate, never disable the DPR fallback, never trigger the select
pass, never write `timing["paths"]`, never add the context block. (b) A dense seed is admitted only when its
passage ranks within the overall top `code_dense_seeds` of **all** passages by `dpr_scores`, not top-N among
code passages. Consequence to state: a prose question over a mixed corpus is byte-identical to today unless a
code passage out-ranks every prose passage on dense similarity, in which case that passage would already have
been a DPR result. Add a test on a mixed fixture (prose + code_sample) asserting a prose question produces
`used_code_seeds == False`, no select call, no `paths` timing key, and the same ranked ids as the prose-only run.

**Ruling 2 — the FIDELITY "scale 0" sentence (V2 blocker).** Adopt V2's stronger alternative: `DEFINED_IN`,
`REFERS_TO`, `MODIFIES`, `CODE_EDGE` **and cross-kind `SYNONYM`** (Entity–Symbol, Entity–DataObject,
Symbol–Symbol, …) are all multiplied by `code_structural_scale`, so scale 0 removes every code vertex from
igraph (`build_igraph` keeps only `weight > 0`). `TUNED` is exempt, as it always is (a user set it). Update the
S2.3 table: `DEFINED_IN` becomes `1.0 × code_structural_scale`. Rewrite the FIDELITY sentence so it is literally
true under this rule, and keep the mixed-fixture test from Ruling 1 as its check.

**Ruling 3 — S2.7 `extract_text` (V2: "literal rule disables OpenIE on all prose").** Three-valued, backward
compatible: `extract_text: str | None = None`. `None` → OpenIE sees `text` (today's behaviour; positional
`Chunk(ordinal, title, text)` keeps working unchanged). `""` → skip OpenIE. Non-empty → OpenIE sees that string.
Only the code chunker ever sets it: docstring/doc-comment when ≥ 80 chars, else `""`. `chunk_documents` for
prose does not touch it. The `test_indexer.py` assertion becomes: chat_json calls == 2 × (prose chunks + code
passages with non-empty `extract_text`).

**Ruling 4 — S2.15 context block drops the subsystem label.** Keep the triple grammar; append, after
`Commits:`, one `Subsystems:` block with one line per community present among the block's symbols:
`<label>: <qualname>, <qualname>, …` (label = the canonical community label from S2.10). Cut rule unchanged.

**Ruling 5 — S2.17 golden file vs non-reproducible SHAs.** Two changes: (a) the fixture builder sets
`GIT_AUTHOR_NAME/EMAIL/DATE` and `GIT_COMMITTER_NAME/EMAIL/DATE` to fixed values so SHAs are stable across
machines; (b) `expected.json` keys commits by `(ordinal, subject)` and MODIFIES by `(ordinal, path, qualname)`,
never by SHA, and the comparison test maps SHAs through the ordinal. (a) is belt-and-braces; (b) is the rule.

**Ruling 6 — history depth (V2 fix on D22 vs S2.11).** `code_history_depth` is a **setting** (`DEFAULT_SETTINGS`,
`SETTING_RULES (int, 0, 2000)`, `SETTING_HELP`), read at index time; `Config.git_history_depth` is removed
from the plan. One spelling everywhere.

**Ruling 7 — everything else in V2.** Apply as recommended. Where V2 says "state the chosen definition", state
it in the section V2 cites, not in the appendix. Where V2's item is a `nit` about A's inherited wording, apply
V2's annotation text.

## When done

Run the self-check (paths exist or `new`; one spelling per setting name: `grep -o 'code_[a-z_]*' PLAN.md | sort | uniq -c`).
Report `[opus-3] V2 applied: <blockers>/<fixes>/<nits> fixed, <declined> declined, PLAN.md <n> lines` and keep
the pane open: one final mechanical re-check (V3) will follow on the finished file.

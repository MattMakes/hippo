# Brief: CDK S2b-fix — emitted labels on identity-only foreign endpoints (ruling R70)

Read `ai_docs/handoffs/fleet-worker-rules.md` first. Use the worktree recipe with name `s2b-fix`
(branch `wp/s2b-fix`, base = the `rag-it-all-tibs` HEAD named in the spawn message). Read
`ai_docs/gates/rag-it-all/cdk/evidence-s2b.md` (its gotchas: the `emit`/`keys` import order and
`render`'s `TYPE_CHECKING` import) and ruling R70 in `ai_docs/plans/cdk-rulings.md`.

GOAL: a connector may give an identity-only foreign endpoint a label. `NodeRef` (`connectors/base.py`)
gains `label: Text | None = None`; the binder's minimal observation for such an endpoint
(`connectors/emit.py`) stores it in `attributes_json` under `label`; `render.edge_statement` (or
the binder's call into it) uses that label when present and the readable canonical key otherwise,
so a statement stays re-derivable from stored records. Nothing else changes.

FILES:
  - own: `src/hippo/connectors/base.py` (the one field), `src/hippo/connectors/emit.py` and
    `src/hippo/connectors/render.py` (the label path only), `tests/unit/test_connector_contract.py`
    (one field test), `tests/unit/test_connector_emit.py` and `tests/unit/test_connector_render.py`
    (the new tests); new `ai_docs/gates/rag-it-all/cdk/evidence-s2b-fix.md`.
  - do NOT touch: anything else, in particular `keys.py`, `classify.py`, `sync.py`, `guard.py`,
    `http.py`, `credentials.py`, `loader.py`, `src/hippo/knowledge/**`, `tests/fakes/**`.

STEPS: worktree + venv (the rulebook recipe, with the `mcp==2.1.1` pin). RED: a test that an
identity-only endpoint with a label yields an observation carrying it and an edge statement
reading "<subject> affects service checkout", and a test that without a label the statement names
the readable canonical key (the current behaviour, which must not change). GREEN. Then the CK2
CHECK line of `ai_docs/gates/rag-it-all/cdk/GATES.md` verbatim and the CK7 Ruff lines; one commit
"Carry an emitted label on identity-only foreign endpoints". Evidence file: RED and GREEN log paths
and counts.

CONSTRAINTS: the rulebook (pytest form with `-W error` and logs, never Neo4j, never `pkill -f`,
stage only owned files, never push, rebase or merge). The totality test's `SPEC_FIELDS` set is
unchanged (a label is not a specification field of `Edge`; it is `Node.label` supplied on the
reference). Binder purity and determinism are unchanged. No duration language.

DONE WHEN: the CK2 line and Ruff exit 0; `horch done` names the commit, counts and log paths.

REPORT: `horch tell orchestrator "[<role>] BLOCKED: ..."` only for a question the brief and the
rulings do not answer.

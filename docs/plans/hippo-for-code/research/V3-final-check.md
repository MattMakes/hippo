# V3 final mechanical re-check

| id | count checked | defects |
|---|---:|---:|
| V1.1 Paths | 90 path targets/references | 1 |
| V1.2 Symbols | 36 existing targets/signatures | 0 |
| V1.3 Store parity | 22 methods/loaders | 0 |
| V1.4 DDL | 12 statement shapes | 0 (3 non-PASS shapes are explicitly gated) |
| V1.5 Settings | 11 settings | 0 |
| V1.6 Tests | 23 test files | 1 |
| V1.7 Contracts | 1 proposed block | 0 |
| V1.8 Internal consistency | settings, paths, relations, weights, fixtures, decisions | 9 |
| V3.1 One spelling per setting | 36 code_* tokens; 11 settings | 2 |
| V3.2 Relation table vs prose | all named relation/scale occurrences | 1 |
| V3.3 Decision Log vs body | D1-D25 | 3 |
| V3.4 S2/S3 rulings landed | 18 S2 items + 7 S3 rulings | 6 |
| V3.5 Pinned tests | 15 assertions/lines | 0 |
| V3.6 Fixture and expected.json | tree, key scheme, git identity | 2 |
| V3.7 Review appendix | 6 V1 + 22 V2 entries | 7 |

## Defects

- **[blocker]** PLAN.md:595 — names docs/design/, docs/design/README.md, docs/design/code-hipporag-design.md and docs/design/code-only-design.md as deliverables, but none exists, none is marked new, and none is assigned to WP4's Files to create at line 413 — should mark all three files new and assign them to WP4 (all four paths fail test -e; V1.1 requires every absent target to be marked new).
- **[blocker]** PLAN.md:106,257 — says the load-time formula is max(fact_count, mention, synonym_score, omega × code_structural_scale), leaving synonym_score outside the scale — should distinguish unscaled Entity-Entity synonym score from scaled cross-kind synonym score, matching PLAN.md:113,128 and Ruling 2 (tasks/S3-v2-rulings.md:20-25).
- **[blocker]** PLAN.md:399 — says dense seeds are the top code_dense_seeds code passages by DPR rank, which is top-N among code passages — should admit a code passage only when it is inside the overall top code_dense_seeds of all passages, matching PLAN.md:123 and Ruling 1 (tasks/S3-v2-rulings.md:13-18).
- **[fix]** PLAN.md:148 — says “the five ingest budgets ... are settings” — should say there are now six ingest budgets, of which code_history_depth, code_git_timeout_s and code_history_total_s are settings and the three code_max_* budgets are constants (PLAN.md:338-349).
- **[fix]** PLAN.md:349 — says “Both” ingest-time settings and excludes only code_history_depth and code_git_timeout_s from Analyze — should exclude all three ingest-time settings, including code_history_total_s, from SIMULATABLE_SETTINGS (PLAN.md:144-146; V2-decision-review.md:393-397).
- **[fix]** PLAN.md:401 — specifies a Subsystems block and then says “The community label is no longer rendered” — should remove the stale final sentence; Ruling 4 requires the label to render in Subsystems (tasks/S3-v2-rulings.md:34-36).
- **[fix]** PLAN.md:492 — assigns the expected.json indexing comparison to test_store_code.py — should assign it to WP2's test_indexer.py, matching PLAN.md:268,280 and the recorded V2 response at PLAN.md:623 (V2-decision-review.md:404-408).
- **[fix]** PLAN.md:613 — says code_history_depth has SETTING_RULES bound (int, 0, 5000) — should be (int, 0, 2000), matching PLAN.md:144,342,634 and Ruling 6 (tasks/S3-v2-rulings.md:43-45).
- **[fix]** PLAN.md:550 — says unresolvable calls produce “no edge and no record” — should retain the per-file unresolved count in CodeGraph.stats() → meta["code"], matching D15 at PLAN.md:49 and the claimed applied V2 response at PLAN.md:641 (V2-decision-review.md:240-242).
- **[fix]** PLAN.md:393,399 — requires both split-question halves to be recorded and constructs expanded RankedPassage rows with via_expand=True, but the declared Trace/RankedPassage field list omits the two split fields and via_expand — should name those fields and give each a backward-compatible default, as S2.12/S2.14/S2.16 require (tasks/S2-staff-decisions.md:101-106,113-130; src/hippo/hipporag/retriever.py:429-444).
- **[fix]** PLAN.md:642 — the finished plan is 642 lines — should be reduced below 600 lines to satisfy the binding S2 instruction (tasks/S2-staff-decisions.md:3-7; wc -l PLAN.md = 642).
- **[nit]** PLAN.md:492,626 — repeats both the expected.json ordinal/subject key rule and the fixed six-variable git identity in the body and Review responses — should leave each normative rule stated once and make the appendix point to line 492; the two copies currently agree, but V3.6 explicitly requires single-source statements.

## V1.1 path inventory

“new” means absent and explicitly marked new. The four docs/design rows are the defect above. Rejected alternatives such as tests/fixtures/code_repo/ are not implementation targets.

| path | in plan as | exists? | verdict |
|---|---|---:|---|
| src/hippo/codegraph/ | new package | no | new |
| src/hippo/codegraph/__init__.py | create/new | no | new |
| src/hippo/codegraph/model.py | create/new | no | new |
| src/hippo/codegraph/treesitter.py | create/new | no | new |
| src/hippo/codegraph/python.py | create/new | no | new |
| src/hippo/codegraph/typescript.py | create/new | no | new |
| src/hippo/codegraph/resolve.py | create/new | no | new |
| src/hippo/codegraph/data_access.py | create/new | no | new |
| src/hippo/codegraph/extract.py | create/new | no | new |
| src/hippo/codegraph/git_history.py | create/new | no | new |
| src/hippo/store/code.py | create/new | no | new |
| src/hippo/hipporag/anchors.py | create/new | no | new |
| src/hippo/hipporag/paths.py | create/new | no | new |
| src/hippo/web/routes/code.py | create/new | no | new |
| src/hippo/store/ladybug.py | modify | yes | exists |
| src/hippo/store/__init__.py | modify | yes | exists |
| src/hippo/store/base.py | modify | yes | exists |
| src/hippo/store/memory.py | modify | yes | exists |
| src/hippo/store/changesets.py | modify | yes | exists |
| src/hippo/hipporag/graph_index.py | modify | yes | exists |
| src/hippo/hipporag/indexer.py | modify | yes | exists |
| src/hippo/hipporag/retriever.py | modify | yes | exists |
| src/hippo/hipporag/answerer.py | modify | yes | exists |
| src/hippo/hipporag/text.py | modify | yes | exists |
| src/hippo/ingest/chunker.py | modify | yes | exists |
| src/hippo/ingest/pipeline.py | modify | yes | exists |
| src/hippo/ingest/readers.py | modify | yes | exists |
| src/hippo/ingest/repos.py | modify | yes | exists |
| src/hippo/ask.py | modify | yes | exists |
| src/hippo/prompts.py | modify | yes | exists |
| src/hippo/analysis/explain.py | modify | yes | exists |
| src/hippo/analysis/simulate.py | modify | yes | exists |
| src/hippo/analysis/changesets.py | modify | yes | exists |
| src/hippo/evals/question_maker.py | modify | yes | exists |
| src/hippo/evals/runner.py | modify | yes | exists |
| src/hippo/mcp_server.py | modify | yes | exists |
| src/hippo/cli.py | modify | yes | exists |
| src/hippo/remote.py | modify | yes | exists |
| src/hippo/status.py | modify | yes | exists |
| src/hippo/web/ | existing contracts area | yes | exists |
| src/hippo/web/app.py | modify | yes | exists |
| src/hippo/web/routes/graph.py | modify | yes | exists |
| src/hippo/web/routes/sources.py | modify | yes | exists |
| src/hippo/web/routes/analyze.py | modify | yes | exists |
| src/hippo/web/routes/pages.py | modify | yes | exists |
| src/hippo/web/static/graph.js | modify | yes | exists |
| src/hippo/web/static/analyze.js | modify | yes | exists |
| src/hippo/web/templates/settings.html | modify | yes | exists |
| src/hippo/web/templates/graph.html | modify | yes | exists |
| src/hippo/web/templates/source.html | modify | yes | exists |
| src/hippo/web/templates/analyze.html | modify | yes | exists |
| src/hippo/web/templates/partials/answer.html | modify | yes | exists |
| tests/fixtures/ | explicitly absent; create | no | new |
| tests/fixtures/code_sample/ | create/new | no | new |
| tests/fixtures/code_sample/expected.json | create/new | no | new |
| tests/unit/test_store_code.py | create/new | no | new |
| tests/unit/test_codegraph.py | create/new | no | new |
| tests/unit/test_git_history.py | create/new | no | new |
| tests/unit/test_anchors.py | create/new | no | new |
| tests/unit/test_paths.py | create/new | no | new |
| tests/unit/test_web_code.py | create/new | no | new |
| tests/fakes/fake_store.py | modify | yes | exists |
| tests/fakes/fake_ollama.py | existing reference | yes | exists |
| tests/conftest.py | modify | yes | exists |
| tests/unit/test_store_ladybug.py | modify/grow | yes | exists |
| tests/unit/test_store_row_shapes.py | modify/grow | yes | exists |
| tests/unit/test_store.py | modify | yes | exists |
| tests/unit/test_graph_index.py | modify | yes | exists |
| tests/unit/test_store_graph.py | modify | yes | exists |
| tests/unit/test_access.py | modify | yes | exists |
| tests/unit/test_ingest_chunker.py | modify | yes | exists |
| tests/unit/test_indexer.py | modify | yes | exists |
| tests/unit/test_ingest_pipeline.py | modify | yes | exists |
| tests/unit/test_ingest_repos.py | existing reference | yes | exists |
| tests/unit/test_retriever.py | modify | yes | exists |
| tests/unit/test_ask.py | modify | yes | exists |
| tests/unit/test_analysis_simulate.py | modify | yes | exists |
| tests/unit/test_analysis_changesets.py | existing pinned assertion | yes | exists |
| tests/unit/test_analysis_explain.py | modify | yes | exists |
| tests/unit/test_mcp_server.py | modify | yes | exists |
| tests/unit/test_web_busy_pages.py | existing coverage reference | yes | exists |
| docs/CONTRACTS.md | modify | yes | exists |
| docs/FIDELITY.md | modify | yes | exists |
| docs/MCP.md | modify | yes | exists |
| docs/design/ | deliverable, not marked new | no | defect |
| docs/design/README.md | deliverable, not marked new | no | defect |
| docs/design/code-hipporag-design.md | deliverable, not marked new | no | defect |
| docs/design/code-only-design.md | deliverable, not marked new | no | defect |
| README.md | modify | yes | exists |
| pyproject.toml | modify | yes | exists |

## V1.2-V1.7 supporting checks

- Existing signatures remain where the plan says: Retriever.retrieve at src/hippo/hipporag/retriever.py:160, index_source at src/hippo/hipporag/indexer.py:64, chunk_documents at src/hippo/ingest/chunker.py:39, clone_repo at src/hippo/ingest/repos.py:58, answer_question at src/hippo/hipporag/answerer.py:26, and ask.search/answer_from_trace at src/hippo/ask.py:23,40. All proposed parameters are additive.
- Store parity is still explicit at PLAN.md:223-235: LadybugStore, Neo4j CodeQueries and FakeStore receive the same 22 method/loader names and the same shared row shapes.
- DDL: T4's additive table statements are PASS (R4-spike-results.md:98-115); T6's endpoint ALTER is PASS (R4-spike-results.md:140-159); T7 is PARTIAL (R4-spike-results.md:161-180), and PLAN.md:202-211 now says so. The production DataObject→DataObject literal and populated/propertied SYNONYM/TUNED ALTER remain unproved but are gated by test 1.5a. RENAME/DROP remains unproved and PLAN.md:219 correctly requires a spike before use. These are flags, not new defects, because the final plan no longer presents them as PASS.
- All 11 settings at PLAN.md:136-146 have defaults and SETTING_RULES bounds; PLAN.md:148/349 requires SETTING_HELP and Settings-page wiring. The two contradictory classification sentences are defects listed above.
- All six new test filenames are absent, so there are no collisions. Store matrices are stated globally at PLAN.md:175 and locally for WP1, WP2, WP2b and WP3. The golden-test owner conflict at PLAN.md:492 is the sole V1.6 defect.
- The CONTRACTS block at PLAN.md:563-591 matches the fenced, left-aligned format at docs/CONTRACTS.md:338-343.

## V3.1 setting-name audit

The mandated grep produced 36 distinct code_* tokens. Eleven are settings; all occur outside the Settings table and use one spelling:

| setting | table line | use outside table |
|---|---:|---:|
| code_seed_weight | 136 | 122-124,399,403,405 |
| code_structural_scale | 137 | 106-128,257,399-405,421-423 |
| code_theta | 138 | 58,397,421 |
| code_dense_seeds | 139 | 123,399,403,405 |
| code_triples_chars | 140 | 401,403 |
| code_community_boost | 141 | 45,399,421,536 |
| code_select | 142 | 128,399,403,512 |
| code_expand_max | 143 | 399 |
| code_history_depth | 144 | 56,342,349,373-379,548,599 |
| code_git_timeout_s | 145 | 343,349,377,548 |
| code_history_total_s | 146 | 344,349,377 |

The code_max_files, code_max_file_bytes and code_max_symbols_per_source tokens are deliberately constants at PLAN.md:345-347. The other grep hits are fields, helpers, fixtures or prose labels, not settings. No setting is table-only or WP-only.

## V3.2 relation and scale audit

| relation | authoritative PLAN locations | result |
|---|---|---|
| CODE_EDGE | 76,102,111,128,257 | agrees except the generic formula defect |
| DEFINED_IN | 78,112,128,230,259,353 | stored omega 1.0; igraph term scaled |
| REFERS_TO | 79,100,114,118,128,231,353 | scaled consistently |
| MODIFIES | 77,99,115,118,128,231,377 | scaled consistently |
| SYNONYM | 69,80,110,113,128,241,353 | Entity-Entity unscaled; cross-kind scaled, except the generic formula defect |
| PRECEDES | 77,116,118,231,375 | excluded from igraph; side-list only |

The disagreement required by V3.2 is explicit: PLAN.md:106 says “synonym_score” is an unscaled max term, while PLAN.md:113 says cross-kind synonym_score is multiplied by code_structural_scale. PLAN.md:257 repeats the unqualified formula. The quoted FIDELITY sentence at PLAN.md:128 and Ruling 2 agree with line 113, not with lines 106/257.

## V3.3 Decision Log cross-check

| decision | implementing section(s) | result |
|---|---|---|
| D1 | 65-85,179-272 | same choice |
| D2 | 76,185-237 | same choice |
| D3 | 76,95,229,237 | same choice |
| D4 | 85,300 | same choice |
| D5 | 120,257 | same choice; denominator clarified |
| D6 | 257,391 | same choice |
| D7 | 284,353 | same choice |
| D8 | 342,369-381 | same choice |
| D9 | 98,284,360 | same choice |
| D10 | 399-403 | same gate; dense admission has an S3 defect |
| D11 | 141,353,397,401,421 | contradiction at 401 |
| D12 | 555 | same choice |
| D13 | 47,555 | same choice |
| D14 | 546,555 | same choice |
| D15 | 49,550 | contradiction: counted vs “no record” |
| D16 | 555 | same choice |
| D17 | 423 | same choice |
| D18 | 124,395,399 | same choice |
| D19 | 401 | same choice |
| D20 | 150-169,389,397,413 | same choice |
| D21 | 393,417-419 | same choice |
| D22 | 132-148,257,338-349,537,593 | formula/classification defects; normative bound is 2000 |
| D23 | 555 | same choice |
| D24 | 87-102,360 | same choice |
| D25 | 437-503 | same fixture; golden-test owner conflict |

## V3.4 S2 and S3 landing matrix

| item | PLAN implementation | result |
|---|---:|---|
| S2.1 | 243-255 | landed |
| S2.2 | 185,241 | landed |
| S2.3 | 106-116 | formula defect |
| S2.4 | 120,257 | landed |
| S2.5 | 259-267 | landed |
| S2.6 | 286-300 | landed |
| S2.7 | 351-353,362 | landed as overridden by Ruling 3 |
| S2.8 | 302-336,360 | landed |
| S2.9 | 375-379,548 | landed |
| S2.10 | 353,360,513 | landed |
| S2.11 | 338-349 | landed; setting prose defect |
| S2.12 | 393,403,593 | behavior landed; trace fields unnamed |
| S2.13 | 395,403 | landed |
| S2.14 | 399,403 | behavior landed; via_expand field omitted |
| S2.15 | 401,403 | stale contradictory sentence |
| S2.16 | 399,403 | generic rule landed; field-list defect |
| S2.17 | 280,492 | key rule landed; test owner conflicts |
| S2.18 | 264,355,399,417,599 | landed |
| Ruling 1 | 122-123,403 | WP3.3 dense-admission contradiction |
| Ruling 2 | 106-128 | edge-formula contradiction |
| Ruling 3 | 351-353,362 | landed; old rule survives only as rejected explanation |
| Ruling 4 | 397,401 | stale “no longer rendered” sentence |
| Ruling 5 | 492 | landed; duplicate in appendix |
| Ruling 6 | 56,144,342,375 | landed; appendix retains wrong old bound |
| Ruling 7 | 620-641 | six response/body mismatches listed above |

The overridden S2.7, S2.15 and S2.17 prescriptions are no longer normative: line 351 quotes the old S2.7 only to reject it, line 401 uses the Ruling 4 Subsystems grammar, and line 492 uses ordinal-based commit keys. The stale sentences and owner conflict are listed as defects.

## V3.5 pinned-test verification

| pinned location | current assertion/content | result |
|---|---|---|
| tests/unit/test_indexer.py:55 | exact counts dict | exact |
| tests/unit/test_indexer.py:98 | exact idempotent counts dict | exact |
| tests/unit/test_indexer.py:212-222 | two exact empty/blank counts dicts | exact |
| tests/unit/test_indexer.py:238 | exact no-facts counts dict | exact |
| tests/unit/test_indexer.py:317 | exact counts dict | exact |
| tests/unit/test_store.py:107 | set(store.stats()) == keys | exact |
| tests/unit/test_ingest_pipeline.py:138 | archive chunk titles | exact |
| tests/unit/test_ingest_pipeline.py:205 | repo chunk titles | exact |
| tests/unit/test_retriever.py:135 | top-node kinds equality | exact |
| tests/unit/test_retriever.py:136 | timing keys equality | exact |
| tests/unit/test_analysis_changesets.py:47 | VALID_OPS equality | exact |
| tests/unit/test_analysis_explain.py:114 | edge kinds equality | exact |
| tests/unit/test_mcp_server.py:17 | five-name TOOL_NAMES set | exact |
| README.md:228 | “the four MCP tools” | exact |

No pinned line drifted. The 212-222 range contains two assertions, giving 15 assertions across the 14 table rows.

## V3.6 fixture and V3.7 appendix

- The fixture tree is defined once at PLAN.md:441-490.
- The ordinal/subject and ordinal/path/qualname key scheme and the fixed author/committer identity are mutually consistent at PLAN.md:492 and with Ruling 5. They are each repeated in the appendix at PLAN.md:626, violating the exact-once rule but not disagreeing.
- Every V1 appendix row at PLAN.md:609-614 maps to a real finding in research/V1-path-check.md. The line 613 response has drifted from the final 2000 bound.
- Every V2 appendix row at PLAN.md:620-641 maps to a real finding in research/V2-decision-review.md. Responses at 620,621,623,625,634 and 641 do not fully match the current body for the reasons in the defect list; the other responses do.

## Final count

**3 blockers, 8 fixes, 1 nit.**

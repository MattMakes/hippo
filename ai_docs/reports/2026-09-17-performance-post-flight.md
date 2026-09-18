# Post-flight report: retained performance and QA work

## Verdict

**CLEAR under the user-approved 16/18 scope.** The original 18/18 quality requirement was not met. It is preserved as two abandoned strict gates, not relabeled as a pass. The retained production result passed 16 fixed cases; Q8 omitted three names that were present in its evidence, and S4 changed one accented Unicode value. On 2026-09-17 the user explicitly accepted those limitations and ended further optimization.

Abandoned gates, verbatim:

- Answer evidence G3 — `ABANDON: G3 User explicitly accepted closure at 16/18 on 2026-09-17 with Q8's three supplied names omitted and S4's accented Unicode value changed; the original 18/18 requirement remains unmet and is future work.`
- Dedicated QA G3 — `ABANDON: G3 User explicitly accepted closure at 16/18 on 2026-09-17 with Q8's three supplied names omitted and S4's accented Unicode value changed; the original 18/18 requirement remains unmet and is future work.`

This verdict means the revised retention decision is fully documented and its focused checks pass. It does not mean that the abandoned 18/18 criterion passed, that quality is universal, or that the two known misses were fixed.

## Summary dashboard

| Category | Status | Evidence |
|---|---|---|
| Gates | PASS under revised scope | 9 met, 2 abandoned, 0 unmet across three ledgers |
| Plans | PASS | Original criteria retained; closure sections record the revised decision |
| Wiring and guards | PASS | Dedicated QA final error-boundary review found no remaining defect |
| Evidence and citations | PASS | Answer-evidence final review found no remaining static defect |
| Selector contract | PASS | Independent review plus five normal 47-49-token production probes |
| Focused tests | PASS | 4, 91, 13, 184, 85 and 430 cases passed in the final reverify commands |
| Unit coverage accounting | PASS with stated history | 5,607 collected: 5,572 passed and 35 skipped across the full run and focused reruns; not one green full-suite invocation |
| Production fixed evaluation | ACCEPTED WITH LIMITS | All 18 completed normally; 16 passed independent source-backed grading |
| Application source | UNCHANGED BY CLOSEOUT | `src/hippo/ollama.py` remains SHA-256 `bf1aa2cd23fa94def7e3a37f999d8e6b412b967c268e4c3013eb71c393d79067` |

## Phase 0: gates and plan conformance

### Dynamic gate re-verification

The gate checker ran with `UNLAZY_APPROVAL_DIR=/private/tmp/hippo-gate-approvals`, `--approve --reverify`, repository root/cwd, and a 600-second timeout. Logs are `/tmp/hippo-final-closeout-selector.log`, `/tmp/hippo-final-closeout-evidence.log`, and `/tmp/hippo-final-closeout-qa.log`.

Met gates:

- Compact selector G1 — `HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_selector_candidate_ids.py -q -o addopts=''`: 4 passed in 0.02s.
- Compact selector G2 — focused retriever/ask/original-citation check: 91 passed with one known warning in 15.10s.
- Compact selector G3 — manual production evidence: Q1, Q2, Q3, Q4 and Q11 completed normally in 47-49 tokens, returned only exact candidate members, and passed the retained full evaluation.
- Answer evidence G1 — focused answer-context check: 13 passed in 0.04s.
- Answer evidence G2 — focused retrieval/citation/authorization/session check: 184 passed with one known warning in 16.46s.
- Answer evidence G4 — manual revised acceptance records 16/18 and both known limitations.
- Dedicated QA G1 — exact profile wiring and error handling: 85 passed in 0.62s with warnings treated as errors except the exact permitted alias warning.
- Dedicated QA G2 — focused compatibility check: 430 passed in 35.94s under the same warning policy.
- Dedicated QA G4 — manual revised acceptance retains the opt-in profile with the measured limitations.

There are no unmet gates. Answer evidence G3 and dedicated QA G3 are abandoned exactly as quoted in the verdict because both required 18/18.

### Plan conformance

- ✅ **Compact selector** — per-call decimal labels, exact membership translation, stable fallback and the existing request budget match the plan; focused checks, independent review and the five production probes pass.
- ✅ **Bounded answer evidence** — ranked-base preservation, bounded lexical graph walk, resolved-original budgets, citations and authorization match the plan; the final static review found no remaining defect.
- ✅ **Dedicated QA profile** — explicit optional final-QA model, single direct request, 4096-token cap, completion enforcement, capability lookup, guard preservation and unchanged default path match the plan and final independent review.
- ⚠️ **Original quality acceptance** — both relevant plans required 18/18; actual independent grading is 16/18. The appended closure sections preserve that history and record the later user-approved scope change.

No broad suite or build was rerun during closeout because the source was unchanged and existing focused unit coverage already covered the retained work. The authoritative unit accounting remains 5,607 collected cases, 5,572 passed and 35 skipped across the full invocation and complete focused reruns. The earlier full invocation's ten non-passing nodes were two stale helper fixtures and eight managed-sandbox socket cases; their complete modules subsequently passed. This is not represented as one green final suite.

## Phase 1: focused static verification

- **Wiring resolution:** PASS. Configuration flows through `Config` and `AppContext` to the existing guarded Ollama client; ask and replay pass the optional QA model through the same answer path. Independent review found no unresolved runtime seam.
- **Behavior and contracts:** PASS for the retained implementation. The default four-message/base-model path, answer fields, citation order, trace shapes, selector fallback, bounded evidence rules and public error classifications are preserved. The opt-in path is one direct final-QA call; no two-call review integration was retained.
- **Error boundaries:** PASS. The final error review verified bounded capability/chat failures and preservation of typed guard/profile exceptions and their public classification. The earlier two review findings are fixed.
- **Configuration consistency:** PASS. Empty `HIPPO_QA_MODEL` inherits the default base 8B path. A nonempty value opts only final answering into its configured model; the evaluated value was the 27.3B `qwen3.8:latest` profile. Retrieval, extraction and other model roles remain on the base model.
- **Credential sources:** PASS/no change. The retained work introduced no credentials or alternate credential source.
- **Backends:** claims are limited to the fake and Ladybug checks that ran. No Neo4j validation is claimed.
- **Dead interfaces:** no new interface or registration was introduced by these retained changes, and the independent final reviews reported no concrete dead wiring.

## Phase 2: runtime evidence

The parent fixed18 run exited 0 and completed all 18 ordered cases. Each case produced exactly one successful configured-QA response with normal terminal completion and nonempty public content. Provider final text and the public answer matched, cited and retrieved identifiers resolved in the authorized export, the source export was substantively stable, and the final manifest recorded stable application source and model identities. Independent grading passed 16/18, with only the two limitations stated above. Private detailed evidence remains under `/private/tmp/hippo-final-eval-qa-profile-run` and is not reproduced here.

The production-body equivalence proof separately passed all six accepted diagnostic bodies through `answer_question`, `AuthorizedModel` and the real Ollama HTTP adapter using a mock transport. It captured six chats and twelve authorization validations, kept the base client unchanged, and selected `qwen3.8:latest` with `think=false`. That proof is wiring evidence, not a substitute for the fixed18 quality result.

## Accepted risks and future work

- Q8 may omit explicitly requested named members even when they are supplied in evidence.
- S4 may alter an exact accented Unicode value.
- Correcting those cases is future work. The fixed question set and oracle must remain unchanged, and any future claim of strict acceptance must rerun source-backed fixed18 grading.

## Phase 3: reflection

Lessons and proposed future checks are recorded in `ai_docs/reflections/2026-09-17-performance-reflection.md`. No global gate defaults or skill files were changed.

# R3 — Retriever, edge weights, explain, changesets, simulate, ask, fidelity

Worker: opus-1. Every path and line number below was re-checked programmatically against the working
tree after the file was written (113 `file:line` citations, 0 problems); snippets are verbatim. Bare file
names are relative to `src/hippo/` unless the path says otherwise. A's claims are cited by work package,
B's by section number. This file runs ~500 lines rather than ~400: the extra length is the per-claim
evidence for the five places where A and B get *different* verdicts (R3.1, R3.3, R3.4, R3.8, R3.10),
which are split into sub-ids rather than merged into one row.

## Verdict table

| id | claim (short) | verdict | key file:line |
|---|---|---|---|
| R3.1 | `retrieve()` order of operations as A and B describe it | Built | `src/hippo/hipporag/retriever.py:193`–`372` |
| R3.1-A | A: symbol seeds enter after the filter, before the fallback decision, and bypass `linking_top_k` | Built (fits the code; needs the fallback line moved, which A states) | `retriever.py:261` |
| R3.1-B | B: `seed_nodes` added to `phrase_weights` "after node specificity and boosts", subject to `link_top_k` | Contradicted | `retriever.py:261`, `retriever.py:301` |
| R3.2 | `Trace` fields and where each is filled; where `anchors`/`paths` join | Built | `retriever.py:110`–`134` |
| R3.3 | `Edge.weight` rule; `graph_with_edits` applies `TUNED` | Built | `graph_index.py:69`–`73`, `graph_index.py:401`–`412` |
| R3.3-AB | A's and B's weight rules are "the same rule"; neither changes a code-free graph | Partial (same shape, differ on `structural_scale`, θ, vertex kind); no-code claim Built | `graph_index.py:73`,`416` |
| R3.3-omega | B: the structural term carries "the confidence ω that a fact count cannot express" | Contradicted | `graph_index.py:73` + B §3 D2/D3 |
| R3.4-A | A: code-node specificity `1/(incoming INVOKES/READS/WRITES + 1)` | Partial (new code path; does not touch prose) | `retriever.py:286`, `graph_index.py:144` |
| R3.4-B | B: keep `1/passage_count`, rely on `MENTIONS`/`DEFINES` | Partial (needs `DEFINES` to write MENTIONS) | `store/memory.py:406` |
| R3.5 | `explain.py` fields, `why` sentences, subgraph `kinds` (the UI does draw them), ≤3-hop path | Built | `analysis/explain.py:27`–`274`, `analyze.js:23` |
| R3.6 | `VALID_OPS`, `validate`, `describe`, `apply`, store methods, version bump | Built | `analysis/changesets.py:21`–`153` |
| R3.6-409 | B: `apply` refuses (409) on eval-set regression; an `eval_set_id` link | Missing | `store/changesets.py:31`–`32` |
| R3.6-sy | `add_synonym` persistence today | Partial (survives until `remove_orphans`) | `store/memory.py:177`, `store/ladybug.py:527` |
| R3.7 | `Overrides` fields; filter replay source; rank diff | Built (today's fields) | `analysis/simulate.py:31`–`57`, `125`–`134`, `140`–`171` |
| R3.7-seed | B: `Overrides` gains `seed_nodes: dict[str, float]` ("try an anchor by hand") | Missing | `analysis/simulate.py:35`–`41`, `112`–`120` |
| R3.7-set | B: `replay_set` runs `runner.run_question` with the filter replayed, no LLM | Contradicted (data exists, the call path does not) | `evals/runner.py:99`,`107`,`113` |
| R3.8 | `search` / `answer_from_trace` signatures and passage shaping | Built | `ask.py:23`–`53`, `answerer.py:26`–`33` |
| R3.8-prompt | B: the QA prompt needs no change for a prepended synthetic passage | Built (prompt), Contradicted (B's placement breaks pinned tests) | `prompts.py:355`, `tests/unit/test_ask.py:55` |
| R3.9 | A: an LLM "select pass" after retrieval; is there one today? | Missing | `retriever.py:149`, `answerer.py:28` |
| R3.10 | `docs/FIDELITY.md` sentences constraining PPR, damping, weights, seeding, `link_top_k`, DPR fallback | Built | `docs/FIDELITY.md:55`–`78`, `116`–`127` |
| R3.10-B | B §14: "with `structural_scale = 0` and no code sources the system is the reference" | Partial (true but vacuous; the useful reading is false) | `retriever.py:205`, `graph_index.py:172` |
| R3.11 | Analyze API endpoints and shapes | Built (no `/api/explain` exists) | `web/routes/analyze.py:165`–`242` |

---

### R3.1: `Retriever.retrieve` end to end — the exact order of operations

**Source:** A §3.4 / B §6
**Evidence:** `src/hippo/hipporag/retriever.py`, stage by stage:

0. empty-index guard → fallback trace, returns — **180–183**
1. read settings (`link_top_k`, `damping`, `passage_node_weight`, `node_specificity`, `retrieval_top_k`) — **185–191**
2. question embedding, once, `kind="query"` — **195–200**
3. `dpr_scores` = min-max(passage_embeddings @ q); `dpr_order`, `dpr_rank_of` — **201–203**
4. `fact_scores` = min-max(fact_embeddings @ q); `full_order` — **205–206**
5. `sent` = top `link_top_k` facts; trace keeps `max(TRACE_CANDIDATES, link_top_k)` — **210–211**
6. `llm_fact_filter` (or a replay) → `kept_triples`; `match_triples(...)[:link_top_k]` — **214–220**
7. `force_include` / `force_exclude` on `kept_fact_indices`; `trace.fact_candidates` — **228–258**
8. **DPR fallback decision** `if not kept_fact_indices:` → rank by DPR and **return** — **261–272**
9. seed entities: fact score ÷ `entity_passage_count` (specificity), ÷ occurrences — **279–291**
10. boosts (`index.entity_boost` overridden by `node_boosts`) multiply `phrase_weights` — **293–298**
11. `link_top_k` cut over `seeded = flatnonzero(occurs > 0)`; the rest zeroed — **300–321**
12. passage seeds `dpr_scores * passage_node_weight`; `reset = phrase + passage`; second fallback when `reset.sum() <= 0` — **324–346**
13. PPR — **350**; passage scores, ranking, `top_nodes` with `seed_vertices` — **354–369**

```python
261:        if not kept_fact_indices:
291:        phrase_weights = np.divide(weight_sum, occurs, out=np.zeros(n), where=occurs != 0)
298:        phrase_weights *= boosts
301:        top_entities = sorted(seeded, key=lambda v: -phrase_weights[v])[:link_top_k] if link_top_k else seeded
338:        reset = phrase_weights + passage_weights
```

**Verdict:** Built
**Implication for the plan:** `link_top_k` does three different jobs — how many facts reach the filter
(210), how far the kept list is cut (218), how many *entities* keep a weight (301). Any plan sentence
saying "subject to `link_top_k`" must say which.

### R3.1-A: A's "symbol seeds bypass the fact filter and `linking_top_k`", inserted after the filter and before the fallback decision

**Source:** A §3.4
**Evidence:** `src/hippo/hipporag/retriever.py:261` — the fallback returns before any seed vector exists:
```python
        if not kept_fact_indices:
            trace.used_dpr_fallback = True
```
**Verdict:** Built (as a description of what must change)
**Implication for the plan:** A's insertion point is the only one that works when every fact dies in the
filter (a bare stack trace), and A correctly notes the fallback condition must become
`not kept_fact_indices and not trace.used_code_seeds`. Bypassing the 301 cut is a real deviation from
`get_top_k_weights` and belongs in `docs/FIDELITY.md` as a new adaptation, not as "no change".

### R3.1-B: B's `seed_nodes: dict[str, float]` added to `phrase_weights` after specificity and boosts, "not exempt from `link_top_k`"

**Source:** B §6
**Evidence:** `retriever.py:261` (returns first) and `retriever.py:300`–`301`:
```python
        seeded = [v for v in np.flatnonzero(occurs > 0)]
        top_entities = sorted(seeded, key=lambda v: -phrase_weights[v])[:link_top_k] if link_top_k else seeded
```
**Verdict:** Contradicted
**Implication for the plan:** Two problems. (1) Placement: "after node specificity and boosts" is line
≥298, which is *after* the fallback `return` at 272 — a question with anchors but no surviving facts
never reaches the anchor code, so B's headline case (a pasted stack trace) silently DPR-falls-back.
(2) `link_top_k`: the cut at 301 iterates `seeded`, which is defined by `occurs > 0` (fact occurrences).
Anchors have no `occurs`, so "not exempt from `link_top_k`" means either putting anchors into `seeded`
— where they compete with fact entities for the same five slots and can evict them — or a second,
parallel top-5 budget. B does not say which; the synthesizer must pick.
**For `docs/FIDELITY.md`:** neither reading is "like the reference does with fact entities" (B §6).
`docs/FIDELITY.md:71`–`72` describes `get_top_k_weights` cutting the *fact-derived* entity set; a separate
anchor budget is not that rule, and sharing the budget lets an anchor evict a fact seed, which changes the
reference ranking on any question that has both. B's anchors are a new adaptation either way, exactly as
A's bypass is (R3.1-A). The dead-code problem above is scoped to questions where *no* fact survives; a
question with some kept facts does reach B's anchor code.

### R3.2: `Trace` — every field and where it is filled

**Source:** A §3.4 / B §6
**Evidence:** `src/hippo/hipporag/retriever.py:110`–`125`:
```python
class Trace:
    question: str
    settings: dict[str, Any]
    graph_version: int
```
| Field | Filled at | Notes |
|---|---|---|
| `question`, `settings`, `graph_version` | 179 | `settings` is the merged dict; it is the simulation baseline (`simulate.py:101`) |
| `used_dpr_fallback`, `fallback_reason` | 181–182, 262–267, 340–341 | three distinct causes |
| `fact_candidates` | 247–258 | one row per fact in `shown` |
| `filter` | 221–225 | `{raw_response, kept_triples, replayed}` — `replay_filter` reads `kept_triples` |
| `seed_entities` | 303–318, sorted 318 | only fact-derived entities exist here today |
| `seed_passages` | 326–336 | top `TRACE_SEED_PASSAGES = 10` by DPR |
| `top_nodes` | 358–369 | top `TRACE_TOP_NODES = 40`, `is_seed` from `seed_vertices` (357) |
| `passages` | 268 / 342 / 356 via `_ranked` (374–392) | |
| `timing_ms` | `embed` 200, `filter` 220, `ppr` 351, `total` 270/344/370 | |

**Verdict:** Built
**Implication for the plan:** `anchors` would be a sibling of `seed_entities`, and `paths` a sibling of
`top_nodes`. Both are read by `trace_from_dict` (429–445), which builds each list with `Cls(**row)`, so
**every new field needs a default** or old stored traces fail to load (`FactCandidate(**c)` at 440 has no
tolerance for missing keys either — a *removed* key breaks old traces, an added one with a default is fine).
`explain.py:66` and `simulate.py:188`–`195` read `trace.seed_entities` only, so anchors kept in a separate
list are invisible to `linked_seeds`, the explanation paths and the simulate diff's seed rows until those
three call sites are extended.

### R3.3: the edge weight rule, and `graph_with_edits`

**Source:** A "Design summary" / B §3 D3
**Evidence:** `src/hippo/hipporag/graph_index.py:69`–`73`:
```python
    @property
    def weight(self) -> float:
        if self.tuned is not None:
            return self.tuned
        return max(float(self.fact_count), 1.0 if self.mention else 0.0, self.synonym_score)
```
`graph_with_edits` copies every `Edge` and sets `tuned` on the edited pairs (`graph_index.py:405`–`411`):
```python
        changed = {k: Edge(**vars(v)) for k, v in self.edges.items()}     # 405
            e = changed.setdefault((min(a, b), max(a, b)), Edge())         # 410
            e.tuned = float(edit.weight)                                   # 411
```
`build_igraph` (415–420) drops any pair whose `weight` is not `> 0`.
**Verdict:** Built
**Implication for the plan:** an edit of weight 0 removes the edge rather than zero-weighting it, and an
edit can create a brand-new pair (hence `explain.py:252`'s `["tuned"]` fallback).

### R3.3-AB: are A's and B's weight rules the same rule?

**Source:** A "Design summary"; B §3 D3
**Evidence:** A: `tuned if set else max(fact_count, 1.0 if mention, synonym_score, ω_max)`.
B: `max(fact_count, mention, synonym_score, structural × structural_scale)`, "tuned still wins".
**Verdict:** Partial — the same shape, three differences
**Implication for the plan:** (1) B multiplies by a `structural_scale` setting, A does not — with A the
only way to turn structure down is to re-index. (2) B adds `omega_threshold` (edges below it "are loaded
but get weight 0"); A has `code_theta` but only for the *path tools and the answer block*, explicitly not
for PPR. (3) The pairs the term lands on differ: under A a code edge joins `Symbol`/`DataObject`/`Commit`
vertices, which carry no `Fact` rows, so `ω_max` is the only term; under B a structural edge lands on the
same `Entity`–`Entity` pair that D2's fact already links.
**Neither changes a graph with no code** (the sub-claim both plans make): a fourth `max` term defaulting to
`0.0` cannot raise a max (`graph_index.py:73`) and `build_igraph` keeps only `e.weight > 0` (`:416`), so an
all-zero term adds no edges. That holds only while `omega_threshold` is applied to the structural term
alone — applied to the whole `Edge.weight` it would change prose, because `add_synonym` accepts any score
`> 0` (`analysis/changesets.py:65`–`67`) and `set_edge_weight` any `weight >= 0` (`:62`), so a prose
edge of 0.3 would be silenced by a default θ of 0.5.

### R3.3-omega: B's claim that the structural term expresses "the confidence ω that a fact count cannot express"

**Source:** B §3 D3, verbatim: "Because D2 already produces a fact edge (count 1) for every call, the
structural term matters for two things: relations that are not facts (`MODIFIED_BY`, `TESTED_BY`,
`DEFINES`) and the confidence ω that a fact count cannot express."
**Evidence:** `graph_index.py:186` sets `e.fact_count += int(row["weight"])`, so D2's per-call Fact makes
`fact_count >= 1`; `graph_index.py:73` then computes `max(1.0, structural × structural_scale)`.
**Verdict:** Contradicted (the second half of the sentence)
**Implication for the plan:** with `structural_scale = 1.0` (B's default) and ω ≤ 1.0 by B §4.3, the ω
term can never exceed the fact term, so ω is invisible to PPR on exactly the pairs D2 creates. Raising
`structural_scale` above 1 is the only way to make ω bite — and a float setting cannot be raised above 1
from the Settings page today (`web/templates/settings.html:76` hard-codes `max="1"`, which A §3.1 already
flags for `code_seed_weight`). Symmetrically, lowering `omega_threshold`'s effect to 0 cannot remove a
fuzzy (ω 0.5) call edge from PPR, because the fact edge keeps weight 1.0. A does not have this problem
because its `CODE_EDGE` pairs carry no `Fact` rows.

### R3.4-A: code-node specificity = `1 / (incoming INVOKES/READS/WRITES + 1)`

**Source:** A "Design summary"
**Evidence:** today's rule, `src/hippo/hipporag/retriever.py:286`–`287`:
```python
                if node_specificity and index.entity_passage_count[v] > 0:
                    w /= index.entity_passage_count[v]
```
fed by `graph_index.py:144` `passage_count[i] = float(row.get("passage_count") or 0)`.
**Verdict:** Partial
**Implication for the plan:** a *second* specificity formula beside the reference one, selected by node
kind. It cannot touch the prose path (entity vertices never have code in-edges), so
`docs/FIDELITY.md:67`–`72` stays literally true for prose. The cost: the retriever needs an in-degree
count per code vertex that `GraphIndex` does not compute today.

### R3.4-B: keep `1/passage_count`, let `MENTIONS`/`DEFINES` count as mentions

**Source:** B §4.2 ("`DEFINES` … also counted as a mention so specificity and access rules hold")
**Evidence:** `src/hippo/store/memory.py:406`:
```python
                   count { (e)<-[:MENTIONS]-() } AS passage_count, e.created_at AS created_at
```
**Verdict:** Partial
**Implication for the plan:** B is the smaller deviation — the retriever code at 286 is untouched and one
formula serves both node kinds — but it is not free: the count query above sees `MENTIONS` only, so
`DEFINES` must either also write a `MENTIONS` row or this query (and its LadybugDB twin) must change.
Neither variant touches the prose path: A adds a branch that prose never takes, B changes only what the
store counts for symbol rows. B is the smaller deviation *against `docs/FIDELITY.md`*; A is the smaller
deviation against the store.

### R3.5: `analysis/explain.py`

**Source:** B §7
**Evidence:** `src/hippo/analysis/explain.py`:
- `PassageExplanation` (31–43): `passage_id, title, rank, score, dpr_rank, linked_seeds, path, path_ids, why`.
- `Explanation` (46–53): `passages, subgraph, facts`, plus `to_dict()`.
- `why` is built by exactly three helpers: `_why_direct` (173–179, "Directly mentions seed 'x' (weight
  0.42)"), `_why_path` (182–190, "Reached in 2 hops from seed 'denver' via 'colorado'.") and `_why_gone`
  (193–197); the DPR-fallback sentence is written inline at 106–109.
- shortest path: `_path_from_strongest_seed` (154–170) — `graph.get_shortest_paths(..., weights=None)`,
  first seed (strongest) that lands within `MAX_PATH_HOPS = 3` (27) wins:
```python
        if path and len(path) - 1 <= MAX_PATH_HOPS:
```
- subgraph (203–255): seeds + `trace.top_nodes` + explained passages, then every edge among them; the
  edge's `kinds` come from `Edge.kinds` (`graph_index.py:76`–`86`), defaulting to `["tuned"]` when the
  pair exists only in an edited graph (252).
**Verdict:** Built
**Implication for the plan:** `anchors` attaches to `Explanation` beside `passages`; `paths` likewise.
`why` sentences for anchors/paths are two more helpers next to `_why_direct`/`_why_path`. `explain()`
reads `trace.seed_entities` (66) and nothing else for seeds, so an anchor list must be joined in
explicitly. B's "the Analyze picture already draws `kinds`" is **Built**: `web/static/analyze.js:23`
labels every edge with `(e.kinds || []).join('+')`, so a `struct:invokes` kind renders with no JS change;
only the per-kind styling selector (`analyze.js:38`) is new, and `graph.js:121`–`123` colours only
`tuned`/`synonym`, so a structural kind falls through to the default colour on the 3D page.

### R3.6: `analysis/changesets.py`

**Source:** B §7
**Evidence:** `src/hippo/analysis/changesets.py:21`:
```python
VALID_OPS = {"set_setting", "set_edge_weight", "add_synonym", "set_node_boost"}
```
`REQUIRED_KEYS` (24–29) demands *exact* key sets (`keys != REQUIRED_KEYS[kind]` → refuse, 55–56).
`validate` (35–45) numbers the offending op. `apply` (118–153) maps each op to one store call:
`store.update_settings` (134) · `store.set_edge_weight` (137) · `store.add_synonyms([...], manual=True)`
(140) · `store.set_node_boost` (143), then:
```python
147:    changed["graph_version"] = store.bump_graph_version()
148:    ctx.invalidate_graph()
149:    store.mark_applied(changeset_id)
```
`describe` (159–179) renders one line per op and resolves ids to names via `store.get_entities` /
`store.get_passages` (182–200).
**Verdict:** Built
**Implication for the plan:** `apply` bumps `graph_version` exactly once, after all ops. New ops are cheap
to add (one `elif` in `_validate_op`, `apply` and `describe`) but `REQUIRED_KEYS` means an optional key
like B's `source_id?` on `add_binding_rule` needs the exact-keys rule relaxed. B's **409 on eval-set
regression is Missing**: the stored `Changeset` carries only `from_result_id` — one *result*, not a set
(`store/changesets.py:31`–`32`) — and `apply` has no gate beyond `validate`. The API maps `ValueError` to
400 (`web/routes/analyze.py:234`–`235`), so a 409 needs a new exception type or an explicit raise.

### R3.6-sy: how `add_synonym` persists today

**Source:** B §1 ("Gap"), B §7 ("survives re-index (today it does not)")
**Evidence:** `changesets.py:140` writes a `SYNONYM` edge with `manual=True`; `store/memory.py:391`
(`s.manual = coalesce(s.manual, false) OR $manual`) keeps the flag. But `remove_orphans`,
`src/hippo/store/memory.py:177` (and `src/hippo/store/ladybug.py:527`):
```python
        self.run("MATCH (e:Entity) WHERE NOT (e)<-[:MENTIONS]-() DETACH DELETE e")
```
**Verdict:** Partial — B's claim is correct
**Implication for the plan:** the `manual` flag is recorded but is not consulted by `remove_orphans`, and
`delete_passages_for_source` calls it on every re-index (`memory.py:138`). So a manual synonym survives
only as long as both its entities keep a mention. Anything B stores only as a `STRUCT` edge (a `commit`
entity with no `MENTIONS`) would be swept on the next re-index.

### R3.7: `analysis/simulate.py`

**Source:** B §7
**Evidence:** `Overrides` (`simulate.py:31`–`41`): `settings, force_include, force_exclude, node_boosts,
edge_edits, rerun_filter, reanswer`; `from_dict` runs `validate_settings` (48), so **a new setting is only
simulatable once it is in `SETTING_RULES`** (`store/base.py:24`–`32`). `to_ops` (59–73) turns settings,
boosts and edge edits into changeset ops (fact force in/out never become ops). The filter replay reads the
baseline trace, not the store (`simulate.py:125`–`132`):
```python
    kept: list[list[str]] = [list(t) for t in baseline.filter.get("kept_triples") or []]
        return [t for t in kept if t in candidates], "replayed"
```
Ranks are diffed by `diff_traces` (140–171) over the top `DIFF_TOP = TOP_PASSAGES = 10` of each trace,
producing `up`/`down`/`new`/`dropped`/`same` (174–185) plus seed rows, kept facts and fallback flags.
**Verdict:** Built for today's fields; **Missing** for B's `seed_nodes` — the dataclass at 35–41 has no
such field and the `retrieve()` call at 112–120 passes no anchors, so B's "try an anchor by hand" is as new
as `replay_set`.
**Implication for the plan:** the replay is deliberately strict — a triple no longer among the candidates
is dropped (see the comment at 130–131) — so a graph change can silently shrink the kept set. `seed_nodes`
would also be the first `Overrides` field with no `to_ops()` counterpart other than the per-question
`force_include`/`force_exclude` pair (59–73), so the plan must say whether a hand-added anchor is savable
as a changeset op or is per-question only.

### R3.7-set: is a whole-set replay feasible with what is stored?

**Source:** B §7 (`simulate.replay_set(ctx, set_id, overrides)` "runs `runner.run_question` with the LLM
filter replayed from each stored result's trace (no LLM)")
**Evidence:** `src/hippo/evals/runner.py:99`, `107`, `113`:
```python
        trace = search(ctx, text, settings, access)
        answer = answer_from_trace(ctx, trace, access)
            result.update(_grade(ctx, text, expected, answer.answer))
```
and `ask.search` (`ask.py:23`–`29`) has no `fact_filter` parameter at all.
**Verdict:** Contradicted as written; the *data* is sufficient
**Implication for the plan:** `run_question` cannot be reused for a no-LLM replay: it calls `search`
(which always uses the real filter), then `answer_from_trace` (one `chat_text`) and `_grade` (one
`chat_json` judge). What is stored *is* enough for a recall-only replay — `result["trace"]` including
`filter.kept_triples` (`runner.py:100`), the question row's `gold_passage_ids` (95) and `trace.settings` —
so `replay_set` should call `Retriever.retrieve(fact_filter=replay_filter(stored_trace))` and
`metrics.recall_at_k` directly and skip answering/judging. (R2 owns `evals/runner.py`; this is the
retrieval-side dependency.)

### R3.8: `ask.search`, `answer_from_trace`, and how passages are shaped

**Source:** A §3.5 / B §6
**Evidence:** `src/hippo/ask.py:23`–`29` and `40`–`53`:
```python
def search(ctx, question, settings=None, access=None) -> Trace:
    merged = ctx.store.get_settings(); merged.update(validate_settings(settings or {}))
    return Retriever(ctx.graph_for(access), ctx.ollama).retrieve(question, merged)
def answer_from_trace(ctx, trace, access=None) -> Answer:
        passages.append((passage.id, passage.title, passage.text))
```
`answer_question` (`answerer.py:26`–`33`) drops the id when building the prompt and returns
`passage_ids=[pid for pid, _, _ in passages]`; `prompts.qa_messages` (`prompts.py:355`) is generic:
```python
    context = "".join(f"Title: {title}\n{text}\n\n" for title, text in passages)
```
**Verdict:** Built
**Implication for the plan:** a synthetic first passage goes in at `answer_from_trace`
(`ask.py:44`–`49`), which simulations (`simulate.py:121`) and evals (`runner.py:107`) also take — one
insertion point covers all three.

### R3.8-prompt: does the QA prompt need to change? (B says no)

**Source:** B §6
**Evidence:** `prompts.py:353`–`361` takes `(title, text)` pairs and formats `Title: {title}\n{text}` with
no per-passage assumptions. But `tests/unit/test_ask.py:55` and `:60`:
```python
    assert answer.passage_ids == trace.passage_ids()[:5]
    assert len(answer.passage_ids) == 2
```
**Verdict:** Built for the prompt; Contradicted for B's placement
**Implication for the plan:** the prompt text itself needs no change. But `Answer.passage_ids` is derived
from the *same list* the prompt is built from (`answerer.py:33`), so B's "prepend one synthetic passage"
inside `answer_from_trace` would put a fake id into `passage_ids` and break both assertions above. A's
shape — a separate `context_block=""` kwarg on `answer_question`, prepended inside — leaves
`passage_ids` alone. Second constraint: `FakeOllama.answer` (`tests/fakes/fake_ollama.py:253`–`254`)
skips lines starting with `Title:` but still scores every *body* sentence for word overlap, so a
code-graph block's body competes with the real passages for the fake's answer; A's gate (only emit the
block when code seeds fired) is what keeps `test_ask.py:52` (`answer == "Boulder"`) green.

### R3.9: A's LLM "select pass" — is there any post-retrieval LLM rerank today?

**Source:** A "Design summary" + §3.4
**Evidence:** the only model calls on the ask path are `retriever.py:198` (`embed_one`), `retriever.py:149`
(`chat_json`, the fact filter) and `answerer.py:28` (`chat_text`, the answer). Nothing sits between PPR
(`retriever.py:350`) and `_ranked` (356). `docs/FIDELITY.md:77`–`78`:
> Passages ranked by their PPR score; when no fact survives the filter the ranking is
> plain dense passage retrieval (`No facts found after reranking, return DPR results`).
**Verdict:** Missing
**Implication for the plan:** cost today is **1 embed + 1 chat per `search`, +1 chat per `ask`** (evals add
one judge call, `evals/judge.py:40`); a select pass makes it 3 chats per answered question, +1 more if
"expand" needs a second round. Placement: `retriever.py` if the trace must record it and simulations must
replay it (A's choice — `simulate.replay_filter` has no hook for a second reply, so a `select` replay is a
new mechanism); `ask.py` if it is only about what the model reads. Simulations decide it:
`simulate()` re-runs `retrieve()` on every slider move (`simulate.py:112`) but calls `answer_from_trace`
only when `reanswer=True` (`simulate.py:121`). A select pass in `retriever.py` therefore costs an LLM call
per slider move unless gated, while one in `ask.py` would never run in a simulation at all — the Analyze
page could neither show nor replay its decisions. A's `retriever.py` + `code_select` gate is the only
placement that keeps the decisions in the trace. `docs/FIDELITY.md` has no sentence permitting a
post-retrieval step and `:153`–`155` pins "Single-step retrieval only", so this is a new numbered
adaptation. Two tests assert zero chat calls on a replay (`test_retriever.py:190`,
`test_analysis_simulate.py:54`); A's `used_code_seeds` gate is what keeps them green.

### R3.10: what `docs/FIDELITY.md` actually constrains, and B's three "additive" claims

**Source:** B §14
**Evidence:** the constraining sentences, verbatim:
- PPR call + damping — `docs/FIDELITY.md:75`–`76`: "PPR: `graph.personalized_pagerank(vertices=range(n),
  damping=damping, directed=False, weights="weight", reset=reset, implementation="prpack")`, character for character."
- edge weights — `:46`–`49` ("+1 per triple that joins them, counted per passage"; "Passage to entity edge:
  weight 1.0"; synonym "`max(existing, score)`") and `:121` ("recomputed at load time with the same
  `max(fact count, 1.0 if mention, synonym score)` rule").
- seeding + `link_top_k` — `:67`–`72`: "divided by the number of passages that mention the entity … only
  the top `linking_top_k` entities keep their weight (`get_top_k_weights`), the rest are set to 0."
- DPR fallback — `:77`–`78` (quoted in R3.9).
- the precedent for calling an addition harmless — `:121`–`124`: "Two things the reference does not have: a
  `TUNED` edge weight that replaces that number, and a per-entity `boost` multiplier on seed weights. Both
  are 1:1 / absent unless you apply a changeset, so a fresh memory behaves like the reference."
**Verdict:** Built (the sentences exist and say this)
**Implication for the plan:** the house style names the addition *and* the condition under which it is
inert. B's three claims against the code:
1. **structural facts as extra `Fact` rows** — additive in the graph, *not* inert in retrieval: they land in
   `index.fact_embeddings` (`graph_index.py:172`) and are scored and ranked with everything else
   (`retriever.py:205`–`210`), so they compete for the five filter slots on every question, prose included.
2. **anchors as extra reset mass after the seed computation** — inert only when the anchor list is empty;
   see R3.1-B for the placement problem.
3. **`structural` as an extra max term** — genuinely inert at `structural = 0` (R3.3-noop), and largely
   inert at `structural_scale = 1` too (R3.3-omega).
So "with `structural_scale = 0` and no code sources the system is the reference" is **true but vacuous**:
with no code sources there is nothing to scale. The reading people will actually take ("scale 0 with code
indexed ⇒ reference behaviour on that corpus") is **false** by (1) — structural Fact rows are still
embedded, still filtered, still seed entities. The claim needs the checkable form used at `:121`–`124`.

### R3.11: the Analyze/web API surface

**Source:** B §9 (`/api/paths/impact`, `/api/simulate/replay-set`)
**Evidence:** `src/hippo/web/routes/analyze.py` — `router` (pages) and `api = APIRouter(prefix="/api")` (40):

- pages: `GET /analyze?question=&key=` (46) · `POST /analyze` form `question`, runs the model (67) ·
  `GET /analyze/{result_id}` gate `run_evals` (84) · `GET /changesets?open=` gate `edit_graph` (138)
- `POST /api/simulate` — `SimulateBody{question, result_id?, trace_key?, overrides}` (151–155); gate
  `run_evals` only when `result_id` is given (171) — **165**
- `GET /api/changesets` (207) · `POST /api/changesets` — `ChangesetBody{name, ops, from_result_id?, note}`
  (158–162) — **213** · `POST /api/changesets/{id}/apply` (226) · `DELETE /api/changesets/{id}` (238);
  all four gated on `edit_graph`

**Verdict:** Built — and **there is no `/api/explain`**: `explain()` is called inside the page render
(`analyze.py:105`) and inside the `/api/simulate` response (`analyze.py:195`).
**Implication for the plan:** `/api/paths/impact` would be the first read-only JSON endpoint in this file,
so it needs its own gate decision (the page endpoints are ungated; every `/api/changesets*` route requires
`edit_graph`). `/api/simulate/replay-set` sits beside `POST /api/simulate` but cannot reuse `SimulateBody`
(no `set_id`). Error mapping today: `ValueError` → 400 (189, 222, 235), `OllamaError` → 502 (193), missing
row → 404 (174, 181, 231).

## Surprises and gotchas for the synthesizer

1. **`tests/unit/test_retriever.py:136` pins the timing keys exactly**:
   `assert set(trace.timing_ms) == {"embed", "filter", "ppr", "total"}`. A's `timing["paths"]` (§3.4)
   breaks this test on the *prose* fixture unless the key is only written when code seeds fired.
2. **`tests/unit/test_retriever.py:135` pins the node kinds exactly**:
   `assert {n.kind for n in trace.top_nodes} == {"entity", "passage"}`. Green today only because the
   fixture is prose; a shared fixture with code would break it. A's `TopNode.kind ∈ {symbol, data, commit}`
   depends on this staying prose-only.
3. **`tests/unit/test_analysis_changesets.py:47` pins `VALID_OPS` by equality** —
   `assert VALID_OPS == {"set_setting", "set_edge_weight", "add_synonym", "set_node_boost"}`. Every new op
   in B §7 edits this line.
4. **`tests/unit/test_analysis_explain.py:114`** asserts `edge["kinds"] == real.kinds`, so any new entry in
   `Edge.kinds` (`graph_index.py:76`–`86`) must appear on both sides at once.
5. **`phrase_weights` keys are vertices, not phrases** — an `np.zeros(num_nodes)` array indexed by vertex
   (`retriever.py:276`, `291`), so nothing assumes OpenIE phrases; any vertex kind can carry reset mass.
   The name is the only OpenIE assumption, and `SeedEntity.entity_id` leaks it into stored traces and the UI.
6. **`scoped()` keeps an entity vertex only if a mention edge reaches a visible passage**
   (`graph_index.py:317`–`327`) and recomputes specificity from those mentions alone (`:343`). A node whose
   only edges are structural vanishes from every scoped index — access-safe by accident, but a restricted
   user then searches a differently-shaped graph.
7. **A `Fact` is dropped by `scoped()` unless both endpoint entities survive** (`graph_index.py:356`:
   `if shown_in and f.subject_id in idx_of and f.object_id in idx_of`). A structural fact pointing at a
   `commit` or a test-file node with no mentions vanishes for restricted users only. `GraphIndex.load` has
   no such filter — it keeps facts whose entities are missing, and `edge()` (`:177`–`181`) returns `None`.
8. **`trace_from_dict` is strict about extra keys** (`retriever.py:440`–`444` uses `Cls(**row)`), so an old
   stored trace loads only while every new field has a default *and* no field is ever removed. Evals store
   traces permanently (`evals/runner.py:100`).
9. **A float setting cannot exceed 1 from the Settings page** — `web/templates/settings.html:76` hard-codes
   `min="0" max="1"` for any non-integer value, while `SETTING_RULES` allows `passage_node_weight` up to
   10. This already bites `code_seed_weight` (A §3.1 spotted it) and would bite `structural_scale > 1`,
   which R3.3-omega shows is the only setting that makes ω matter under B.
10. **A new setting with no `SETTING_HELP` entry renders a blank hint, it does not crash**
    (`web/routes/pages.py:27`–`35`, Jinja's default `Undefined`), so a missing help line is easy to ship.
11. **`ctx.invalidate_graph()` runs on every apply** (`analysis/changesets.py:148`) and `GraphIndex.load`
    rebuilds everything; `docs/FIDELITY.md:124`–`127` already warns the cost grows with the stored-vector
    count, which symbol-per-function nodes multiply by roughly the number of functions in a repo.
12. **`scoped()` reconstructs `Edge` field by field.** `graph_index.py:371`–`373` writes
    `Edge(fact_count=0, mention=e.mention, synonym_score=e.synonym_score, tuned=e.tuned)`, so a new
    `structural` (B) or code-edge (A) field is silently dropped from every access-scoped index: a
    restricted user gets a differently-*weighted* graph, not merely a smaller one, and no test would catch
    it (the scoped tests assert visibility, not weights). `graph_with_edits` is safe — `Edge(**vars(v))`
    (`graph_index.py:405`).
13. **`simulate()` re-runs the *whole* retrieval** (`simulate.py:112`), question embedding included, on
    every slider move — no cached vector is kept on the trace even though `retrieve` accepts
    `question_embedding` (`retriever.py:170`). Anchors/paths/select in `retrieve` make every slider move
    more expensive unless gated.

# Combined RAG fixture and baseline

This fictional corpus is a **harness diagnostic**, not a product-quality benchmark.
Its 24 questions are hand-authored and pending independent human review. Task 16
must expand to 120 reviewed questions, approve targets and run the privacy and
lifecycle suites before release. No numbers from fake models establish retrieval
quality. Do not tune on the held-out questions.

## Corpus boundaries

Only paths explicitly listed in `manifest.json.sources`, under `corpus/`, may be
indexed. `gold/`, this README, and saved reports are never input documents. The
loader parses all four gold files and rejects gold paths, copies of any gold file,
and embedded question, evidence, object or permission-label structures.
Expected answer facts intentionally overlap source facts; such ordinary overlap is
not leakage. The corpus uses synthetic normalized provider payloads, not captures
claiming exact compatibility with a Jira/Tuleap/GitHub/GitLab deployment. Later
connector tasks add native recorded responses against their endpoint contracts.

Development is the entire `commerce` repository/artifact group: billing and checkout,
tenant-isolated order persistence, PostgreSQL `commerce` and SQL Server `dbo` keys,
a decision about cross-tenant joins, and ownership correction. Holdout is the separate
`fulfillment` group: shipping and tracking, warehouse stock reservation, `logistics`
and `warehouse` schemas, and a decision against promising stock at another location.
It uses different handlers, mutations, constraints, rationale and impact questions.
Shared fixture conventions and public-source audiences are not learned labels.
Neither repository's questions or evidence may cross the artifact-group split.

Both groups contain explicit route registrations; independently uploaded PostgreSQL
and SQL Server DDL; composite keys, a view, and add/drop migration observations;
an unrelated `analytics.orders`; draft/accepted/superseded criteria; a decision table
longer than the pinned 1,500-character chunk setting; normalized ticket edits/deletes
and restricted comment; old/new review diff sides, rename, outdated comment and
truncated diff; manifest, Backstage catalog drift and unknown API reference; OpenAPI
local `$ref`; and conflicting owner observations. Only the primary service has an
explicit release-to-commit mapping; infer none for the second service.

The two audiences are `public` and `operators`; the reader belongs only to public,
while the operator belongs to both. A restricted comment is the sole source for a
service-to-service dependency. `gold/permission_cases.json` defines expected allowed
and forbidden evidence separately from quality scores. These cases are **not a
passing provider privacy suite**: that requires the later ACL/connector tasks.

## Gold schema (version 1)

- `manifest.json`: workspace, schema/review status, principals, two snapshots, exact
  source allow-list, gold-file paths and unapproved release targets. Every source has
  stable ID, path, family, artifact group, audience and snapshot membership. Code
  files additionally share a `repository_id`, so the real parser sees cross-file imports.
- `gold/evidence.json`: stable evidence ID, original `source_id`, exact complete quote
  and `locator: {kind: exact_text, occurrence: 1}`. Each quote must occur exactly once
  in the original source. A retrieved chunk must contain the full quote and belong
  to that original artifact to receive credit. Splitting off half a quoted unit gives
  no credit. Quotes identify original spans; they are never retrieval input.
- `gold/objects.json`: separately authored stable object ID, kind and artifact group.
  These are evaluation identities, not a claim to implement Task 2 canonical IDs.
- `gold/questions.json`: stable question ID, query text, slice, split, artifact group,
  principal, snapshot, query mode, temporal selectors, required object IDs, alternative
  sufficient evidence sets, directed relation paths, answer facts, forbidden claims,
  expected insufficiency (an actual JSON boolean) and required capabilities. Temporal
  selectors require timezone-aware ISO timestamps, including snapshot and nested
  comparison selectors. An outer alternative list is OR;
  all IDs inside one set are AND. Distinct sufficient evidence is acceptable, e.g.
  the original decision row or the independently stated Jira rationale. Empty outer
  gold is legal only for expected insufficiency, and never earns automatic success.
  `INVOKES` uses the existing code graph vocabulary. `as_of` supplies `valid_at` and
  `known_at`; `compare` supplies independent left/right selectors. These are gold
  expectations, not already implemented temporal support.

Object and relation endpoints must exist in the object inventory and stay in their
group. Gold evidence must exist, stay in that group and be visible to the specified
principal. Duplicate question IDs, duplicate evidence IDs, duplicate/empty alternative
groups, missing quotes and artifact-group split leakage are rejected.

## Temporal event log (`temporal_events.jsonl`)

A separate fixture from the corpus above: 16 **recorded events**, one JSON object per
line, covering the nine temporal scenarios of Task 5A (plan section 7 step 3). It is
not a snapshot and not retrieval input. `hippo.evals.rag_all_temporal` replays it into
a knowledge store; `tests/unit/test_temporal_conflicts.py` validates its shape and
`tests/unit/test_temporal_fixture_loader.py` exercises every scenario through it.

Three row shapes, distinguished by which key is present:

- **claim** (`claim`): `case`, `source_id`, `provider_order`, `valid_from`, `valid_to`,
  `recorded_from`, `precision`, `claim: {predicate, object}`, and optionally
  `scope_key`, `content_hash`, `source_updated_at`, `source_precision`.
- **suppression** (`suppression`): `case`, `source_id`, `recorded_from` and
  `suppression: {view_applicability, reason, epoch}`. Ordering metadata is forbidden -
  a suppression is not a revision of a claim. Both sets are closed:
  `view_applicability` is `current_only` or `all_history`, and `reason` is
  `tombstone`, `access_loss` or `purge`.
- **barrier** (`restoration_barrier`): `case`, `source_id`, `provider_order`,
  `restoration_barrier`, `recorded_from`. Its `provider_order` is deliberately in the
  source's *claim* series, so a confirmed restoration can be ranked against ordinary
  arrivals from that source; a barrier row never becomes a conflict candidate, so it
  can never supersede a claim.

Every instant is a timezone-aware ISO string, and its declared offset is preserved:
a `valid_from` of `2026-04-01T02:00:00+02:00` is stored as that text with
`source_timezone="+02:00"` while the computed instant is the UTC one. `precision:
"instant"` and a non-null `valid_from` imply each other, so no row can turn an unknown
effective time into a dated one - and a row with no `valid_from` declares no source
timestamp at all, so it serializes with a null original text and zone rather than with
the instant Hippo recorded it at. `provider_order` carries `adapter`, `version`, `kind`
(`monotonic`/`equality_only`/`unknown`), `ordinal` (an integer exactly when
`monotonic`) and `token` (nonempty exactly when `equality_only`, null when `unknown`).

Any row the loader cannot read as a recorded event - a malformed instant, a closed-set
value it does not know, a missing or unexpected key, or a shape the knowledge model
itself refuses - raises `TemporalFixtureError` naming the row's index in the file.

### What the loader does with a row

`load_temporal_events(store, path, *, clock)` parses with `read_temporal_events`, sorts
by `recorded_from` and applies each event at or before `clock()` - the caller's
statement of now, and the loader's only time input. Later events are returned in
`deferred`, so an incremental replay is just a later clock.

Two rows sharing one instant keep their file order across sources, because an ordinal
is only comparable inside the series that issued it; inside one series the adapter's
ordinal decides, so no closure can be lost to where a row sits in the file. Two rows of
one series that tie on both the instant and the ordinal are refused: the fixture must
declare an unambiguous order. A closure the ordering proves but section 5 cannot
express - a target recorded at the very instant that would close it - is also refused
rather than silently dropped.

- A **claim** becomes one staged generation, published at that row's own
  `recorded_from`. When the row's adapter ordering proves it retires an earlier claim
  of the same source and series, the publication carries a `TemporalPublicationPlan`
  closing the retired segment and appending the new one in one transaction. Nothing is
  ever rewritten, and arrival order never supersedes: `select_same_source` and
  `fully_superseded_version_ids` make every decision, so `old_imported_last` - old bytes
  imported after everything else - closes nothing and stays retained history.
- A **suppression** writes its `Suppression` at the row's instant. `current_only`
  leaves authorized history readable; `all_history` denies it.
- A **barrier** writes nothing of its own: it declares the authoritative
  `restoration_barrier` that its source's suppressions carry. A `Suppression` is
  immutable and `restoration_barrier` is not a mutable field, so barrier rows are
  resolved before any suppression is written rather than by rewriting a committed one.
  Sources with no barrier row get a per-reason default (`tombstone` → `refetch`,
  `access_loss` → `reverify`, `purge` → `destroy`). **A barrier row is the one row
  shape the clock does not bound**: it is a file-level declaration about its source,
  so the May 17 barrier is already what the May 15 tombstone carries. Barrier rows are
  reported in `declarations`, never in `applied` or `deferred`, because neither would
  be true of them.

### Conventions the rows do not carry

The rows argue about one subject and never name it, so the loader supplies:

- subject `service-a` (kind `service`), claim objects of kind `owner`;
- `DEFAULT_SCOPE_KEY = "service-a:production"` for a row with no `scope_key`, which is
  what makes `environment_collision`'s declared `service-a:staging` a genuinely
  distinct scope and `independent_alternative` a genuine alternative;
- `SourceOrder.series_key = source_id`: one ordered revision stream per fixture source.
  The object is deliberately not part of it, so the equal-token pairs land in one series
  and come out ambiguous with a canonical refetch requested;
- `rule_version = "rag-all-temporal-v1:<source>"`, so two sources stating an identical
  undated claim at the same instant do not collapse into one `AssertionVersion` whose
  proof group the first publication already sealed. Cross-source corroboration is
  expressed as separate candidates over the same `Assertion`.

Because supersession is ordinal-only, the catalog series ends at its highest ordinal:
`backdated_correction` (ordinal 3) closes `may_owner_bob` (2), which had itself closed
`may_owner_alice` (1). Every closed segment stays queryable at a cutoff before its
closure - which is exactly what "original before, corrected after" means.

The ordinal rule decides closure alone, so arrival order decides nothing:
`old_imported_last` carries ordinal 1 and arrives last, closes nothing, and is never
current. It stays recorded-open until a higher ordinal publishes, because section 5
closes only a segment recorded strictly earlier than the publication doing the closing
and part 2 forbids closing a member of the publishing generation - so a claim can
never close itself. `restated_new_state` (ordinal 4) is that later publication: it
appends the state after 2026-05-01 that the backdated correction's bounded historical
segment does not assert, and its one plan closes every lower-ordinal open segment of
the series - the re-import *and* the corrected historical segment. From 2026-05-13T06:00Z
onward the catalog therefore proves exactly one claim, the ordinal-4 one; the April
segment remains proven at any earlier `known_at`.

The two purge rows are deliberately different. `purged_history` purges `prd`, whose
only claim is undated and therefore contextual, so no manifest can ever name its
revision: it proves the denial half of section 4. `purged_proven_history` purges
`accepted-prd`, whose claim is time-proven and does enter a pinned `HistoryManifest`,
so it proves the other half - `purged_history_evidence` answers an audience that can
still prove what is left of the manifest with `evidence_purged` markers carrying no
retained text, and answers one that cannot with `SnapshotUnavailable`.

Replaying the same file into the same store is an exact retry: every record the loader
writes is content addressed and an already-published row's generation is observed
rather than republished.

## Deterministic baseline

From the repository root:

```sh
.venv/bin/python scripts/rag_eval.py --fixture tests/fixtures/rag_all --mode legacy --split dev --retrieval-only --output .rag-eval/legacy-dev.json
```

The CLI injects the existing `FakeOllama` HTTP transport and a fresh in-memory
`FakeStore`. Stable source IDs remove UUID-dependent graph tie-breaking. It calls
the production readers, code extractor, chunker, indexer and `search`, including
cross-file code parsing, actual embeddings, OpenIE rules, PPR and its dense fallback.
The packaged `hippo.evals.rag_all` module imports no `tests` modules. Only this explicit
repository development CLI builds test doubles. No existing store, network, model
download or application environment is used. The temporary context is closed afterward.

The static current corpus is the `after` snapshot selected by the harness. Historic
questions remain coverage gaps independently of their optional `requires` labels:
any non-current query, non-`after` snapshot or explicit temporal selector is unsupported.
This is not a temporal implementation. Legacy
source-rank ACL is recorded, but provider policies and restricted supported sources
are skipped rather than made public. Unsupported provider/catalog families are
reported as gaps, not zero-quality working connectors. Typed constraint questions,
provider links, history/conflict and insufficiency remain unmeasured until their
implementations exist. Supported prose/code retrieval misses still score zero;
an extraction miss is not relabeled as a coverage gap.

Reports pin corpus/gold fingerprint, model profile, settings and chunk/retrieval
budgets. They preserve stable original passage/source IDs, titles and ordinal locators
without source text, as well as candidate positions, scores, complete
quoted-evidence mappings, actual PPR/code/dense-fallback route and reasons, per-slice
metrics and per-metric sample counts, indexed counts and gaps. A candidate with no labeled
evidence still occupies a rank; one candidate with multiple units occupies one rank.
Recall is the largest fraction of any sufficient set covered. All-required success
requires a whole alternative. MRR uses the first original passage with any relevant
unit. Binary nDCG uses relevance from any gold unit and an ideal computed from **all
relevant passages in the indexed corpus**, independently of returned rankings.
If the parser produced no relevant passages, nDCG is undefined/omitted but evidence
recall is zero. Pure `evidence_set_metrics` instead grades already deduplicated evidence
rankings; it is not substituted for passage-rank evaluation.

`bm25`, `dense`, `hybrid` and `all` fail with `mode not implemented`. Answer evaluation
without `--retrieval-only` is unimplemented and fails. `--check-targets` fails because
no targets are approved. A split with no evaluable questions fails, never empty success.
Targets and human review cannot be approved by merely writing numbers into a fixture.
Do not run holdout for tuning; the command supports it for later release evaluation.

## Optional separate live-model baseline

This API recipe uses an **empty temporary LadybugDB** and explicit already-installed
Ollama models. It does not load application environment, download models or generate
answers. Capture it separately from deterministic fake diagnostics; availability and
model differences must not affect unit tests. Run only when live inference is intended:

```python
import json
import tempfile
from pathlib import Path
from hippo.config import Config
from hippo.context import AppContext
from hippo.evals.rag_all import evaluate, load_fixture
from hippo.ollama import Ollama
from hippo.store import open_store

with tempfile.TemporaryDirectory(prefix="hippo-rag-live-") as directory:
    config = Config(
        data_dir=Path(directory),
        openie_workers=1,
        ollama_url="http://127.0.0.1:11434",
        llm_model="qwen3:8b",
        embed_model="nomic-embed-text",
    )
    ollama = Ollama(config.ollama_url, config.llm_model, config.embed_model)
    ctx = AppContext(config, open_store(config), ollama)
    try:
        if ollama.missing_models():
            raise RuntimeError("Install the explicitly selected models separately")
        report = evaluate(
            load_fixture("tests/fixtures/rag_all"),
            ctx,
            split="dev",
            model_profile="live:qwen3:8b+nomic-embed-text; record exact model digests",
        )
        output = Path(".rag-eval/legacy-dev-live.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    finally:
        ctx.close()
        ollama.client.close()
```

Record actual Ollama model digests alongside the report before using a live result
for a comparison. The initial fake profile demonstrates deterministic plumbing,
not a replacement for this live evaluation or later reviewed enterprise gold.

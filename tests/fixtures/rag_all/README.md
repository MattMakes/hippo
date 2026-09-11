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
    config = Config(data_dir=Path(directory), openie_workers=1,
                    ollama_url="http://127.0.0.1:11434",
                    llm_model="qwen3:8b", embed_model="nomic-embed-text")
    ollama = Ollama(config.ollama_url, config.llm_model, config.embed_model)
    ctx = AppContext(config, open_store(config), ollama)
    try:
        if ollama.missing_models():
            raise RuntimeError("Install the explicitly selected models separately")
        report = evaluate(load_fixture("tests/fixtures/rag_all"), ctx, split="dev",
                          model_profile="live:qwen3:8b+nomic-embed-text; record exact model digests")
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

# CDK S4a-fix evidence: three kit defects S4b found (ruling R77)

Worker `backend-developer-17`, branch `wp/s4a-fix`, base `bc71f0e` (the `rag-it-all-tibs` HEAD named
in the spawn message, after S4a and S4b merged). Contract: the brief
`ai_docs/handoffs/briefs/cdk-s4a-fix.md` and ruling R77 of `ai_docs/plans/cdk-rulings.md`. Read
first: `evidence-s4b.md` (findings 1–3, gotchas 1, 2 and 4) and `evidence-s4a.md` (gotcha 7).

Each of the three fixes is its own commit, each RED before it and GREEN after it.

## Commits

| # | Hash | Subject | Files |
| --- | --- | --- | --- |
| 1 | `4dfe212` | Count a case's parse failures in failures.json (CDK S4a-fix) | `src/hippo/connectors/testing.py` (`_parse_failures`); `tests/unit/test_connector_testing_kit.py` (one test and one helper); `tests/unit/test_connector_scaffold.py` (one pinned digest, granted) |
| 2 | `9f7da36` | Rewrite the registry lock when a package is re-goldened (CDK S4a-fix) | `src/hippo/connectors/testing.py` (`validate_package`); `tests/unit/test_connector_testing_kit.py` (one test, one `_copied_package` keyword) |
| 3 | `64af318` | Publish the fixture connector's descriptor on the class (CDK S4a-fix) | `tests/fakes/fixture_connector/connector.py` (a class attribute, outside the marked regions); `tests/unit/test_connector_loader.py` (one test) |

The whole diff against `bc71f0e` is five files: `testing.py` (+33/-9, over its two functions),
`connector.py` (+5/-0), `test_connector_loader.py` (+23/-0), `test_connector_scaffold.py` (+1/-1,
the granted digest) and `test_connector_testing_kit.py` (+83/-3). Nothing else was touched: no
`sync.py`, `emit.py`,
`loader.py`, no scaffold template, no committed golden, no `docs/spec` file, no gate ledger
checkbox, no checkpoint, no `data/`, no `.rag-dev-data/`.

### The one grant beyond the brief's "own" list

The brief lists `tests/unit/test_connector_scaffold.py` under "do NOT touch". Fix 1 moves exactly
one of its pins, because S4b's scaffolded package has a malformed `record-2` **by design** and its
`failures.json` was pinned at the digest of `[]`. Measured before asking, asked before committing,
and the orchestrator answered:

> (a) approved: move the one failures.json digest in tests/unit/test_connector_scaffold.py
> PINNED_DIGESTS to 13e34d72... (the scaffold's malformed record now counted), nothing else; name
> it in the evidence with the before and after digests and the fact that the other 17 digests and
> the fixture goldens are unchanged.

| Pin | Before | After |
| --- | --- | --- |
| `fixtures/basic/expected/failures.json` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` (the digest of `[]`) | `13e34d72fc736904d7a816fbb8caf4562d3a8ad32bc55e2b8e407a21ce326d62` |

The scaffolded file now reads `[{"count":1,"family":"incident","parser":null}]`. **The other
seventeen pinned digests are unchanged**, including `fixtures/registry.lock.json`
(`428b518bec4ebec7cfa839fbd91cf48a0cdeb63fd8b127c5a2b73386b2dfcb9d`), which is what proves fix 2
writes the same bytes `scaffold._write_lock` already wrote. `PINNED_SOURCES` does not hold a
golden, so no byte-for-byte pin moved.

## RED

| Item | Log | Result |
| --- | --- | --- |
| 1, `test_a_malformed_record_fills_failures_json` | `/tmp/hippo-cdk-s4a-fix-red-1.log` | exit 1; **1 failed, 84 deselected**. The full `validate_package` passed with no error and no violation, the coverage golden held `"emission": {"failures": {"custom|-|-": 1}}`, and `failures.json` was `[]` — the defect exactly, with nothing else broken |
| 1, the pin this moves | `/tmp/hippo-cdk-s4a-fix-scaffold-1.log` | exit 1; **1 failed, 18 passed**, `scaffold output changed: ['fixtures/basic/expected/failures.json']` — one file, named by the test |
| 2, `test_update_golden_rewrites_a_stale_registry_lock` | `/tmp/hippo-cdk-s4a-fix-red-2.log` | exit 1; **1 failed, 85 deselected**. The stale lock fired `registry_version_bump` on the update run (`predicate:FIXTURE_LINKS@1 changed without a version bump`) instead of being rewritten |
| 3, `test_the_fixture_connector_loads_through_an_entry_point` | `/tmp/hippo-cdk-s4a-fix-red-3.log` | exit 1; **1 failed, 19 deselected**; `AttributeError: type object 'FixtureConnector' has no attribute 'descriptor'` raised inside `loader._imported`, listed as the entry's `error` |

Every RED bit as an assertion on the defect named in R77, not as a collection error.

## GREEN

| Line | Log | Result |
| --- | --- | --- |
| 1, the kit and the scaffold | `/tmp/hippo-cdk-s4a-fix-green-1.log` | exit 0, **104 passed** (kit 85, scaffold 19) |
| 2, the kit and the scaffold | `/tmp/hippo-cdk-s4a-fix-green-2.log` | exit 0, **105 passed** (kit 86, scaffold 19) |
| 3, the loader, the kit and the scaffold | `/tmp/hippo-cdk-s4a-fix-green-3.log` | exit 0, **125 passed** (loader 20, kit 86, scaffold 19) |
| The CK4 CHECK line of `GATES.md`, verbatim | `/tmp/hippo-cdk-s4a-fix-ck4.log` | exit 0, **166 passed** (S4b's 163 plus this slice's three) |
| The CK3 Fake CHECK line of `GATES.md`, verbatim | `/tmp/hippo-cdk-s4a-fix-ck3-fake.log` | exit 0, **296 passed, 2 skipped** — the same counts S4b recorded |
| The kit file on LadybugDB | `/tmp/hippo-cdk-s4a-fix-ladybug.log` | exit 0, **86 passed** |
| Regression, the CK2 Fake CHECK line (it reads the fixture connector) | `/tmp/hippo-cdk-s4a-fix-ck2-fake.log` | exit 0, **289 passed** |
| Regression, the guide, the markers and the scaffold pin by name | `/tmp/hippo-cdk-s4a-fix-guide.log` | exit 0, **5 passed** |
| The CK7 Ruff lines of `GATES.md`, verbatim | run inline | exit 0 and exit 0; "All checks passed!", "39 files already formatted" |
| Ruff over `tests/fakes/fixture_connector/connector.py`, which CK7 does not cover | run inline | exit 0 and exit 0; "All checks passed!", "1 file already formatted" |

Counts for the kit file per backend: **Fake 86**, **LadybugDB 86**, the same cases on both — S4a's
84 plus this slice's two.

**Warning filters.** Every line above ran with `-W error` alone: **form (a)** of rulebook line 19,
and no marker was needed. No file in these lines imports `fastapi.testclient` or
`starlette.testclient` at module level. No warning was suppressed and no ini-wide `filterwarnings`
was added.

**No Neo4j run.** The rulebook forbids one without a written grant, which this worker did not hold.
Nothing here reads `.rag-dev-data/`, a credential, a token, the server on 8011 or the user's Ollama:
every store is a temporary one and the model is `offline_ollama()` over `httpx.MockTransport`.

## The committed goldens and the lock are byte-identical

The brief requires that nothing committed moves. Measured on the finished tree:

```text
git status --porcelain -- tests/fakes/fixture_connector/fixtures   -> empty
git diff --exit-code bc71f0e -- tests/fakes/fixture_connector/fixtures -> exit 0
git diff --stat bc71f0e -- tests/fakes/fixture_connector -> connector.py | 5 +++++
```

| File | SHA-256, unchanged from `bc71f0e` |
| --- | --- |
| `fixtures/registry.lock.json` | `805eef3d7ab4ce47ee41fd123e6cb35e48d44ec1f531b2d55bccf1c8efe4b6af` |
| `expected/aliases.json` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `expected/coverage.json` | `82ad37c28dfd77bb7a4e069199f8da838abaf1fee7891c64a65d560ae9b696e5` |
| `expected/edges.json` | `48d30091e8a58b72149ecd48d000ce859ede7cc9d4fc1f22e294443b46a8a707` |
| `expected/failures.json` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `expected/nodes.json` | `e4dcb264db19992f4e5f51345aca97e8eedeea77a15235cf67ccbfbfb909f0d9` |
| `expected/passages.json` | `8b97e91a77963216235814c3b7a2d4fcca0abfbc8378a200655f10b01c6c43df` |
| `expected/units.json` | `43b959175bb2c7f66ffbd72d8e2b48084409378019477120eb43578c8a14136b` |

The fixture connector's own `failures.json` stays `[]` on purpose: `fixtures/basic` has no malformed
record, and the brief forbids adding one to the committed case. Both new kit tests work on a
`tmp_path` copy of the package (S4a gotcha 7, S4b gotcha 4), and the class attribute of fix 3 sits
outside the `# cdk-guide:` marked regions, so the guide's four fenced blocks still equal their
regions byte for byte (`/tmp/hippo-cdk-s4a-fix-guide.log`).

## What each fix is

### 1. `failures.json` fills (R77, S4b finding 1, S4a open question 3)

`_parse_failures` read `coverage["failures"]`, then `coverage["parse_failures"]`. Neither key is
ever written: `sync._coverage_json` puts `EmissionCoverage.to_json()` under `emission`, and
`emit._count_failures` keys each count `family|parser|dialect`, writing `-` for a part the failure
omits. The kit now reads `coverage["emission"]["failures"]` first and splits the key back into the
plan's `family` and `parser` columns (section "the goldens", `cdk-s4-kit.md` line 416), with `-`
read as "the failure named none". The two old keys are still read after it, so a coverage some
other writer produced is unaffected.

The fixture connector's malformed note produces `{"family": "custom", "parser": null, "count": 1}`:
`FIXTURE_FAMILY` is `custom`, and its `ParseFailure` carries no parser and no dialect. R75(4) now
holds — the file fills the moment a fixture exercises a `ParseFailure`, which is what S6's exemplar
adds.

**The brief asks the test to prove more than the data holds.** It says the row should name "the
parser and the record". A count is all `coverage_json` keeps: `emit._count_failures` sums by
`family|parser|dialect` and no record id, external id or `ParseFailure.reason` survives into the
generation's coverage at all, and the fixture connector's own failure names no parser. The test
therefore asserts the whole row it can — `{"family": "custom", "parser": null, "count": 1}` — plus
the coverage key `custom|-|-` it was read from. A `failures.json` that names records would need
S3c to carry them into the coverage, which is a `sync.py`/`emit.py` change no brief grants.

### 2. `--update-golden` rewrites the registry lock (R77, S4b finding 2 and override 2)

`assert_registry_lock` only compares; it writes nothing. So a developer who added a kind and reran
`--update-golden` got seven recomputed goldens and the eighth committed file left behind, and
`registry_version_bump` then passed vacuously against a lock nobody would move again. On an update
run `validate_package` now writes the lock from `extension_lock(descriptor.extension,
version=descriptor.version)` instead of asserting the one it replaces; on an ordinary run nothing
changes. This is what `scaffold._write_lock` already did by hand for a package `hippo connector new`
had just written, which is why the scaffold's lock digest does not move.

### 3. The fixture connector's `descriptor` is a class attribute (R77, S4b finding 3)

`loader._imported` reads `descriptor` off the class it loads, before anything is constructed, and
`_installed` reads it off the class again. `FixtureConnector` bound it in `__init__` only, so it was
the one connector package in the repository the loader could not load: an entry point pointed at it
answered `AttributeError` and the kind was listed broken. `descriptor = DESCRIPTOR` is now a class
attribute; `__init__` still rebinds it on the instance, so `descriptor_extension` and the kit's own
`kit_patch` subclass (which sets `self.descriptor`) behave exactly as before. S4b's scaffold already
emits a class attribute; S5b's `git` and S6's exemplar must carry one.

## Decisions this slice made that the plan does not name

1. **The dialect is dropped from a failure row.** The coverage key is `family|parser|dialect`, and
   `cdk-s4-kit.md` line 416 pins `failures.json` to three columns — `family`, `parser`, `count`.
   Two failures of one family and parser that differ only in dialect therefore appear as two rows
   with equal `family` and `parser` and their own counts, ordered by the golden's own sort. No
   committed case has a parser or a dialect, so nothing observes this today; a slice that wants the
   dialect has to widen the plan's table first.
2. **The update run writes the lock rather than asserting it first.** An update run that appended
   `registry_version_bump` to its report would make `scaffold.render_package` delete the package it
   had just written, because it refuses any violation on that run (S4b override 3). Re-goldening is
   the act that resolves a stale lock, so the rule is not evaluated on the run that rewrites it.
3. **The lock is written as `canonical_json` with no trailing newline**, matching
   `scaffold._write_lock` and `_diff_goldens`. S4a's committed
   `tests/fakes/fixture_connector/fixtures/registry.lock.json` carries one trailing newline (292
   bytes against the writer's 291), so a `--update-golden` run over the *committed* package — which
   no test does, and which gotcha 7 forbids — would strip that byte. The lock is read with
   `json.loads`, so nothing compares those bytes.

## Findings for the orchestrator

1. **The lock rewrite is silent at the CLI and absent from the guide.** `cli._connector_validate`
   prints `<connector> <version>: goldens written` on an update run and lists the golden diff; the
   lock it now rewrites appears in neither, and `docs/spec/cdk-guide.md` section 7 still says
   `--update-golden` "rewrites them", meaning the seven. Both files are do-not-touch for this
   worker. One line in each, whenever `cli.py` and the guide are next open (S6).
2. **`assert_registry_lock` is still the only writer-free path, and `extension_lock` is still not
   re-exported by the scaffold.** `scaffold._write_lock` and `validate_package` now compute the
   same bytes in two places. If a third caller appears, a public `write_registry_lock` beside
   `assert_registry_lock` is the obvious shape; two callers did not justify widening the kit's
   public surface inside this brief's grant.
3. **S4a's committed lock has a trailing newline the kit's writer does not produce** (decision 3).
   Harmless today; worth normalizing the next time that file is legitimately regenerated.
4. **S5b's `git` connector and S6's exemplar must publish `descriptor` as a class attribute.** R77
   already says so; fix 3 makes the repository's own worked example follow the rule, so a slice that
   copies it inherits the right shape.

## Gotchas for the next worker

1. **Two `failures.json` files answer to different code now.** The fixture connector's stays `[]`,
   because `fixtures/basic` has no malformed record. The scaffolded package's holds one row, and its
   digest is pinned in `test_connector_scaffold.py`, so a change to the scaffold's `emit` template,
   to `_parse_failures` or to S3c's counter moves that pin and nothing else. A change to the fixture
   connector's `emit`, its `types.py` or its case still moves the committed goldens (S4a gotcha 7).
2. **A test that re-goldens must copy the package first**, now more than before: an update run
   rewrites `fixtures/registry.lock.json` as well as the seven goldens, so
   `validate_package(tests/fakes/fixture_connector, update_golden=True)` would rewrite the committed
   lock too.
3. **`_copied_package(tmp_path, verb_phrase=...)`** is the smallest way to move a package's
   vocabulary under an unmoved descriptor version: it patches the descriptor's extension with
   `fixture_links_predicate(verb_phrase=...)`, which moves exactly the
   `predicate:FIXTURE_LINKS@1` lock key.
4. **The fixture connector's instance descriptor still wins.** `descriptor = DESCRIPTOR` on the
   class does not change `FixtureConnector(descriptor_extension=...)`, and any subclass that assigns
   `self.descriptor` keeps shadowing the class attribute.

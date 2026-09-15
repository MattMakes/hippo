"""Generation-scoped store reads: same rows as the unscoped forms, bounded work per call.

The scale defect these cover is plan section 8.1: `native_write` materialised every row of a
kind per call, `native_mutation` every row of all six native kinds, and `_native_relationships`
every relationship in the database. Writing a 50,000-symbol generation in batches was therefore
quadratic in the corpus.

Three things are proven here and each needs its own kind of assertion:

* **Equal results.** Every scoped read returns exactly what the unscoped read returned for the
  same selection. The unscoped form stays available for the legacy lane, so it is its own
  reference oracle -- no copy of the old body can drift away from it.
* **Bounded queries.** A read call is recorded with the scoping key it was given; a call with no
  key at all is a whole-table read. Writing N rows in batches of B must do a constant number of
  reads per batch and no whole-table native read.
* **Bounded CPU.** Query scoping does not fix a Python loop that rescans a list per row, so
  sealing is also measured against a synthetic generation at two sizes.

The semantics that must survive scoping are as important as the speed: `native_write` still
finds a prior untagged row, `native_mutation` still refuses an edge across two generations and
still admits one to an untagged legacy row, and the relationship enumeration still sees both
endpoints of a crossing edge -- a read narrowed to one generation would silently delete those
three guards rather than fail them.
"""

from __future__ import annotations

import ast
import re
import time
from pathlib import Path

import pytest

from hippo.knowledge import model as k
from hippo.store import base, migrations
from tests.unit.test_generation_store import (
    NOW,
    authority,
    claim,
    evidence,
    generation,
    manifest,
    native_fixture,
    passage,
    seal,
)


class ReadLog:
    """Records every scoped read, so a test can assert on the key rather than the row count."""

    def __init__(self, store):
        self.store = store
        self.calls = []
        self._native = store._native_rows
        self._knowledge = store._knowledge_rows
        self._relationships = store._native_relationships

    def __enter__(self):
        def native_rows(kind, **scope):
            self.calls.append(("native", kind, dict(scope)))
            return self._native(kind, **scope)

        def knowledge_rows(name, **scope):
            self.calls.append(("knowledge", name, dict(scope)))
            return self._knowledge(name, **scope)

        def relationships(**scope):
            self.calls.append(("relationships", None, dict(scope)))
            return self._relationships(**scope)

        self.store._native_rows = native_rows
        self.store._knowledge_rows = knowledge_rows
        self.store._native_relationships = relationships
        return self

    def __exit__(self, *exc):
        self.store._native_rows = self._native
        self.store._knowledge_rows = self._knowledge
        self.store._native_relationships = self._relationships
        return False

    @property
    def whole_table(self):
        """Reads that named no scoping key at all: the defect this slice removes."""
        return [call for call in self.calls if not any(value is not None for value in call[2].values())]

    def native_whole_table(self, kind=None):
        return [
            call for call in self.whole_table if call[0] == "native" and (kind is None or call[1] == kind)
        ]

    def knowledge_whole_table(self, kinds=None):
        """Whole-table knowledge reads, optionally only of `kinds` (see `test_knowledge_scoped_reads`)."""
        return [
            call
            for call in self.whole_table
            if call[0] == "knowledge" and (kinds is None or call[1] in kinds)
        ]


def reference_relationships(store, ids):
    """The reviewed whole-database enumeration, kept verbatim as the parity oracle.

    Copied from `GenerationQueries._native_relationships` as merged at 7a0c719, before the
    scoped passes replaced it. It reads every relationship of every kind, which is exactly the
    defect under repair -- its only job here is to say what the answer must be.
    """
    from hippo.knowledge.identity import canonical_json
    from hippo.store.generations import float32_vector

    specs = {
        "CODE_EDGE": ("code_edges", ("Symbol", "DataObject"), ("Symbol", "DataObject")),
        "DEFINED_IN": ("definitions", ("Symbol", "DataObject", "Commit"), ("Passage",)),
        "MODIFIES": ("modifies", ("Commit",), ("Symbol",)),
        "PRECEDES": ("precedes", ("Commit",), ("Commit",)),
        "REFERS_TO": ("refers_to", ("Passage",), ("Symbol", "DataObject")),
        "MENTIONS": ("mentions", ("Passage",), ("Entity",)),
        "STATES": ("statements", ("Passage",), ("Fact",)),
        "SUBJECT": (None, ("Fact",), ("Entity",)),
        "OBJECT": (None, ("Fact",), ("Entity",)),
        "SYNONYM": ("synonyms", ("Entity", "Symbol", "DataObject"), ("Entity", "Symbol", "DataObject")),
        "TUNED": (
            "tuned",
            ("Entity", "Passage", "Symbol", "DataObject"),
            ("Entity", "Passage", "Symbol", "DataObject"),
        ),
    }
    edges = []
    for rel, (attr, left, right) in specs.items():
        if store.knowledge_backend == "fake":
            if attr is None:
                field = "subject_id" if rel == "SUBJECT" else "object_id"
                edges.extend([rel, r["id"], r[field], {}] for r in store.facts.values())
                continue
            values = getattr(store, attr)
            for key in values:
                a, b = key[:2]
                payload = values[key] if isinstance(values, dict) else {}
                edges.append([rel, a, b, payload])
        else:
            for a_kind in left:
                for b_kind in right:
                    if rel == "CODE_EDGE" and (a_kind, b_kind) == ("DataObject", "Symbol"):
                        continue
                    payload_expr = "properties(r)" if store.knowledge_backend == "neo4j" else "r"
                    for record in store.run(
                        f"MATCH (a:{a_kind})-[r:{rel}]->(b:{b_kind}) "
                        f"RETURN a.id AS a,b.id AS b,{payload_expr} AS r"
                    ):
                        edges.append(
                            [
                                rel,
                                record["a"],
                                record["b"],
                                {
                                    key: value
                                    for key, value in dict(record["r"]).items()
                                    if not key.startswith("_")
                                },
                            ]
                        )
    shared = {r["id"]: dict(r) for kind in ("Entity", "Fact") for r in store._native_rows(kind)}
    reachable = set(ids)
    reachable.update(
        endpoint for _, a, b, _ in edges if a in ids or b in ids for endpoint in (a, b) if endpoint in shared
    )
    for relationships in ({"MENTIONS", "STATES"}, {"SUBJECT", "OBJECT"}):
        reachable.update(b for rel, a, b, _ in edges if rel in relationships and a in reachable)
    result = []
    for rel, a, b, payload in edges:
        if not ((a in ids or b in ids) or ({a, b} <= reachable)):
            continue
        if any(endpoint not in ids and endpoint not in shared for endpoint in (a, b)):
            raise ValueError("Native relationship crosses generations")
        result.append([rel, a, b, payload])
    for rid in sorted(reachable - set(ids)):
        if rid not in shared:
            raise ValueError("Missing shared graph endpoint")
        payload = {
            key: value
            for key, value in shared[rid].items()
            if key not in ("created_at", "updated_at") and not key.startswith("_") and value is not None
        }
        if payload.get("embedding") is not None:
            payload["embedding"] = float32_vector(payload["embedding"])
        result.append(["shared", rid, payload])
    return sorted(result, key=canonical_json)


def symbol_rows(store, gen, count, *, start=0):
    from hippo.codegraph.model import symbol_id
    from hippo.knowledge.lifecycle import generation_namespace

    namespace = generation_namespace(gen)
    rows = []
    for index in range(start, start + count):
        path = f"m{index}.py"
        rows.append(
            dict(
                id=symbol_id(gen.source_id, path, "f", "function", node_namespace=namespace),
                source_id=gen.source_id,
                generation_id=gen.id,
                name="f",
                qualname="f",
                kind="function",
                path=path,
                embedding=[0.1, 0.2],
            )
        )
    return rows


# --------------------------------------------------------------- equal results


# A managed passage id is a `sha256` of its binding and a legacy one an `md5` of its chunk, so
# the two lanes leave rows of two different lengths in one table. That difference is what made
# the store defect below visible rather than silent.
LEGACY_PASSAGE_ID = "passage-" + "1" * 32
MANAGED_PASSAGE_ID = "passage-" + "2" * 64
SCRATCH_PASSAGE_ID = "passage-" + "9" * 32


def raw_passage(passage_id, source_id, title):
    return dict(
        id=passage_id,
        source_id=source_id,
        ordinal=0,
        title=title,
        text="ACME builds Robot.",
        embedding=[0.1, 0.2],
    )


def test_native_rows_scoped_by_ids_return_the_unscoped_rows_for_those_ids(store):
    gen = generation(store)
    job = claim(store, gen)
    symbol, row = native_fixture(store, gen, job)
    for kind, rid in (("Symbol", symbol["id"]), ("Passage", row["id"])):
        unscoped = store._native_rows(kind)
        assert store._native_rows(kind, ids=[rid]) == [r for r in unscoped if r["id"] == rid]
        assert store._native_rows(kind, ids=[]) == []
        assert store._native_rows(kind, ids=["absent"]) == []


def test_native_rows_scoped_by_generation_return_the_unscoped_rows_of_that_generation(store):
    gen = generation(store)
    job = claim(store, gen)
    native_fixture(store, gen, job)
    for kind in ("Symbol", "Passage"):
        unscoped = store._native_rows(kind)
        scoped = store._native_rows(kind, generation_id=gen.id)
        assert scoped == [r for r in unscoped if r.get("generation_id") == gen.id]
        assert scoped, f"the {kind} fixture row must be in its own generation"


def test_untagged_rows_of_a_source_are_one_bounded_query(store):
    """Ruling 14's key for the legacy lane: the rows of a source that no generation owns."""
    gen = generation(store)
    job = claim(store, gen)
    symbol, _ = native_fixture(store, gen, job)
    legacy_source = store.create_source("code", "legacy")
    legacy = dict(
        id="sym-untagged",
        source_id=legacy_source,
        name="f",
        qualname="f",
        kind="function",
        path="a.py",
        embedding=[0.1, 0.2],
    )
    store.add_symbols([legacy])

    untagged = store._native_rows("Symbol", source_id=legacy_source, untagged=True)
    assert [row["id"] for row in untagged] == ["sym-untagged"]
    # The managed source's staged row is not untagged, so it is invisible to the legacy lane.
    assert store._native_rows("Symbol", source_id=gen.source_id, untagged=True) == []
    assert symbol["id"] in {row["id"] for row in store._native_rows("Symbol", generation_id=gen.id)}
    # Equal results: the same rows the unscoped read would have been filtered down to.
    unscoped = store._native_rows("Symbol")
    assert untagged == [
        row for row in unscoped if row.get("generation_id") is None and row.get("source_id") == legacy_source
    ]


def test_a_row_cannot_be_both_tagged_and_untagged(store):
    with pytest.raises(ValueError, match="both belong to a generation and be untagged"):
        store._native_rows("Symbol", generation_id="g", untagged=True)
    with pytest.raises(ValueError, match="shared and is not scoped by generation"):
        store._native_rows("Entity", untagged=True)


def deleted_row_then_two_lanes(store):
    """The three-row shape the managed lane meets: a deleted row, a legacy row, one to write.

    A reindex deletes and rewrites the legacy passages, so by the time a managed build runs,
    the Passage table holds a hole. The managed row is written inside the build's own
    transaction and read back before it commits. Both facts are needed to reach the defect
    `test_an_id_scoped_read_answers_from_the_wanted_row...` pins.
    """
    scratch = store.create_source("text", "reindexed")
    legacy_source = store.create_source("text", "legacy")
    managed_source = store.create_source("text", "managed")
    store.add_passages([raw_passage(SCRATCH_PASSAGE_ID, scratch, "Reindexed")])
    store.delete_passages_for_source(scratch)
    store.add_passages([raw_passage(LEGACY_PASSAGE_ID, legacy_source, "Legacy")])
    return managed_source


def test_an_id_scoped_read_answers_from_the_wanted_row_while_its_transaction_is_open(store):
    """The id list may not be a `WHERE` predicate: LadybugDB answers it from another row.

    Probed on real_ladybug 0.15.3: when a node table holds a deleted row *and* the wanted row
    was written inside the open transaction, `MATCH (n:Passage) WHERE n.id IN $ids` selects the
    right row but projects its STRING properties from a different one -- a foreign `title`, an
    `id` cut to another row's length, and `*_json` bytes that are not valid UTF-8, which the
    Python binding raises `UnicodeDecodeError` on while materialising the row. `n.id = $id`,
    `MATCH (n:Kind {id: $id})` and `UNWIND $ids AS rid MATCH (n:Kind {id: rid})` all answer
    correctly in the same state, so every id selection is spelled as a primary-key lookup
    (`base.by_ids`). Merge `c461c9c` pointed `_knowledge_get("Passage", id)` at the `IN` form
    and took the whole managed lane down on Ladybug with it.
    """
    managed_source = deleted_row_then_two_lanes(store)
    with store.transaction():
        store.add_passages([raw_passage(MANAGED_PASSAGE_ID, managed_source, "text.md")])
        rows = store._native_rows("Passage", ids=[MANAGED_PASSAGE_ID])
        assert [row["id"] for row in rows] == [MANAGED_PASSAGE_ID]
        assert rows[0]["title"] == "text.md"
        assert rows[0]["source_id"] == managed_source
        # The reference read that `_knowledge_get` makes for every managed native validation.
        assert store._knowledge_get("Passage", MANAGED_PASSAGE_ID)["title"] == "text.md"
        # Scoping by source must not confuse the two lanes' rows either.
        legacy = store._native_rows("Passage", ids=[LEGACY_PASSAGE_ID])
        assert [row["id"] for row in legacy] == [LEGACY_PASSAGE_ID]
        assert legacy[0]["title"] == "Legacy"


def test_the_public_id_reads_answer_from_the_wanted_row_in_the_same_state(store):
    """The same rule holds for the reads a caller can reach, not only the internal ones."""
    managed_source = deleted_row_then_two_lanes(store)
    with store.transaction():
        store.add_passages([raw_passage(MANAGED_PASSAGE_ID, managed_source, "text.md")])
        found = store.get_passages([MANAGED_PASSAGE_ID])
        assert [row["id"] for row in found] == [MANAGED_PASSAGE_ID]
        assert found[0]["title"] == "text.md"
        assert store.get_passages([MANAGED_PASSAGE_ID, LEGACY_PASSAGE_ID])[1]["title"] == "Legacy"


def code_lines(path):
    """The module's lines with its docstrings and comments removed.

    The rule below is about the Cypher a module builds, and the same words have to be legible
    in the prose that explains the rule -- `base.by_ids` and the LadybugDB module header both
    spell the forbidden shape out. Reading the docstrings out of the file is what lets the
    tripwire quote the defect instead of writing around it.
    """
    source = path.read_text(encoding="utf-8")
    documented = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(getattr(first.value, "value", None), str):
            documented.update(range(first.lineno, first.end_lineno + 1))
    return [
        (number, line)
        for number, line in enumerate(source.splitlines(), 1)
        if number not in documented and not line.lstrip().startswith("#")
    ]


# `r.kind` binds a CODE_EDGE, not a node, and the relationship tables were not shown to have
# the defect: two attempts to build a CODE_EDGE that the trigger could reach came back empty
# (`/tmp/hippo-lbfix-probe-relkind.log`), so `store/code.py` and `ladybug.py`'s in-degree read
# keep their list predicate rather than being rewritten on a guess. Delete this entry the day
# one of them is either proven exposed or rewritten anyway.
UNPROVEN_RELATIONSHIP_LIST_PREDICATES = {"r.kind"}


def test_no_query_builder_selects_node_rows_with_a_list_predicate(store):
    """A tripwire, because the defect is silent: the wrong row comes back, not an error.

    `IN $ids` reads correctly almost everywhere, so a new query written that way passes review
    and passes its own test. Only the three conditions above expose it, and by then the row has
    already entered a checksum. The rule is therefore checked at the source rather than argued,
    over both packages that build Cypher: the store and the knowledge projection that reads
    passages back by generation. `label IN $labels` in `migrations` is a comprehension over
    `labels(n)` rather than a stored column and is not this shape.
    """
    roots = (Path(base.__file__).parent, Path(k.__file__).parent)
    offenders = [
        f"{path.name}:{number} ({match.group(1)} IN ...)"
        for root in roots
        for path in sorted(root.rglob("*.py"))
        for number, line in code_lines(path)
        # Cypher keywords are case-insensitive and any whitespace separates them (R21-m3).
        for match in re.finditer(r"(?i)\b(\w+\.\w+)\s+IN\s+\$", line)
        if match.group(1) not in UNPROVEN_RELATIONSHIP_LIST_PREDICATES
    ]
    assert offenders == [], f"node lists must drive the MATCH (see base.by_ids): {offenders}"


def test_only_an_all_principals_suppression_of_the_source_leaves_the_legacy_lane(store):
    """R21-m10: `source_serves_legacy`'s suppression term, tested directly.

    A suppression naming principals hides the source from those principals and no one else, so
    the source keeps serving its legacy graph; an all-principals suppression in the source's own
    workspace takes it out of the lane.
    """
    source_id = store.create_source("text", "legacy")
    workspace = store.get_source(source_id)["workspace_id"]

    def suppress(**fields):
        store.put_knowledge(
            k.Suppression(
                workspace_id=workspace,
                target_kind="source",
                target_id=source_id,
                epoch=store.suppression_epoch() + 1,
                created_at=NOW,
                restoration_barrier="operation-1",
                **fields,
            )
        )

    assert store.source_serves_legacy(store.get_source(source_id))
    suppress(
        scope_key=f"source:{source_id}:access",
        all_principals=False,
        principal_ids=("user-1",),
        view_applicability="all_history",
        reason="access_loss",
    )
    assert store.source_serves_legacy(store.get_source(source_id))
    suppress(scope_key=f"source:{source_id}:delete", view_applicability="current_only", reason="tombstone")
    assert not store.source_serves_legacy(store.get_source(source_id))


def test_knowledge_rows_scoped_by_generation_return_the_unscoped_records(store):
    gen = generation(store)
    job = claim(store, gen)
    native_fixture(store, gen, job)
    for name in ("GenerationMember", "GenerationEvidenceMember", "NativeBinding"):
        unscoped = store._knowledge_rows(name)
        scoped = store._knowledge_rows(name, generation_id=gen.id)
        assert scoped == [r for r in unscoped if r.generation_id == gen.id]
        assert scoped, f"the {name} fixture row must be in its own generation"


def test_knowledge_rows_scoped_by_where_return_the_unscoped_records(store):
    gen = generation(store)
    job = claim(store, gen)
    native_fixture(store, gen, job)
    seal(store, gen, job)
    source_id = gen.source_id
    events = store._knowledge_rows("IndexEvent")
    assert store._knowledge_rows("IndexEvent", where={"aggregate_id": source_id}) == [
        e for e in events if e.aggregate_id == source_id
    ]
    members = store._knowledge_rows("GenerationMember")
    assert store._knowledge_rows("GenerationMember", where={"id": members[0].id}) == [members[0]]
    assert store._knowledge_rows("IndexEvent", where={"aggregate_id": "absent"}) == []


def test_knowledge_rows_refuse_a_where_field_outside_the_allow_list(store):
    # A free-form filter would be an unindexed scan wearing a scoped read's clothes.
    with pytest.raises(ValueError, match="not a scoped field"):
        store._knowledge_rows("IndexEvent", where={"payload_json": "x"})
    with pytest.raises(ValueError, match="not a scoped field"):
        store._knowledge_rows("Suppression", where={"nonexistent": "x"})


def test_a_kind_specific_scoped_field_is_refused_on_another_kind(store):
    """The allow-list is per kind because the v6 indexes are: one kind each, not all kinds."""
    assert store._knowledge_rows("MaintenanceJob", where={"input_fingerprint": "g"}) == []
    with pytest.raises(ValueError, match="not a scoped field"):
        # SyncRun declares input_fingerprint too, but only MaintenanceJob's is indexed.
        store._knowledge_rows("SyncRun", where={"input_fingerprint": "g"})


def test_every_kind_scoped_field_has_an_index_in_a_journaled_step(store):
    from hippo.store.knowledge import KIND_SCOPED_FIELDS

    indexed = {(label, field) for _, label, field in (*migrations.NATIVE_INDEXES, *migrations.V7_INDEXES)}
    assert {(label, field) for label, fields in KIND_SCOPED_FIELDS.items() for field in fields} <= indexed


def test_native_relationships_scoped_by_generation_equal_the_id_selection(store):
    gen = generation(store)
    job = claim(store, gen)
    symbol, row = native_fixture(store, gen, job)
    ids = {symbol["id"], row["id"]}
    assert store._native_relationships(generation_id=gen.id) == store._native_relationships(ids=ids)


def test_native_relationships_refuse_a_call_with_no_scope(store):
    with pytest.raises(ValueError, match="scoping key"):
        store._native_relationships()


def test_generation_checksums_are_unchanged_by_scoping(store):
    """The seal is the byte-identity anchor: a manifest built before must verify after."""
    gen = generation(store)
    job = claim(store, gen)
    native_fixture(store, gen, job)
    checksums = store.generation_checksums(gen.id)
    assert {c.kind for c in checksums} == {"evidence", "dense", "native"}
    assert all(c.row_count > 0 for c in checksums)
    # Recomputation is stable, and the seal re-verifies the same bytes through _verify_manifest.
    assert store.generation_checksums(gen.id) == checksums
    seal(store, gen, job)
    assert store.generation_checksums(gen.id) == checksums


def test_scoped_relationships_equal_the_reviewed_unscoped_enumeration(store):
    """`_native_relationships` is the one helper whose *algorithm* changes, so it gets an oracle.

    Generation ids are random, so no golden checksum can be pinned. Instead the reviewed
    whole-database enumeration is kept verbatim in `reference_relationships` and the scoped
    passes must reproduce it row for row, including the shared-graph closure rows.
    """
    gen = generation(store)
    job = claim(store, gen)
    symbol, row = native_fixture(store, gen, job)
    other = generation(store, key="two")
    other_job = claim(store, other, key="job-2")
    other_symbol, other_row = native_fixture(store, other, other_job)
    for selection in ({symbol["id"], row["id"]}, {other_symbol["id"], other_row["id"]}):
        assert store._native_relationships(ids=selection) == reference_relationships(store, selection)
    # A selection that cuts an edge in half must still raise, and raise the same way.
    for partial in ({symbol["id"]}, {row["id"]}):
        with pytest.raises(ValueError, match="Native relationship crosses generations"):
            reference_relationships(store, partial)
        with pytest.raises(ValueError, match="Native relationship crosses generations"):
            store._native_relationships(ids=partial)


def test_two_code_edge_kinds_between_one_pair_are_both_enumerated(store):
    """R21-B5: a `CODE_EDGE` exists once per `(a, b, kind)`, so one pair can carry two.

    A module-level `main()` call is both CONTAINS and INVOKES, and a function that selects and
    updates one table both READS and WRITES it. De-duplicating the scoped passes on the endpoint
    pair dropped the second kind on LadybugDB and Neo4j only -- the Fake store keys its edges by
    kind -- and the sealed checksum, the projection and the source's edge counts all read it here.
    """
    gen = generation(store)
    job = claim(store, gen)
    symbol, row = native_fixture(store, gen, job)
    [callee] = symbol_rows(store, gen, 1, start=7)
    with store.generation_write(gen.id, **authority(job)):
        store.add_symbols([callee])
        store.add_code_edges(
            [
                {"a": symbol["id"], "b": callee["id"], "kind": kind, "omega": omega, "provenance": "syntax"}
                for kind, omega in (("CONTAINS", 1.0), ("INVOKES", 0.5))
            ]
        )
    selection = {symbol["id"], row["id"], callee["id"]}
    scoped = store._native_relationships(ids=selection)
    assert {edge[3]["kind"] for edge in scoped if edge[0] == "CODE_EDGE"} == {"CONTAINS", "INVOKES"}
    assert scoped == reference_relationships(store, selection)
    assert store._native_relationships(generation_id=gen.id) == scoped


# ------------------------------------------------------- preserved semantics


def test_native_write_still_finds_a_prior_untagged_row(store):
    """The generation falls back to the prior row's, so legacy updates keep working."""
    source = store.create_source("code", "legacy")
    row = dict(
        id="sym-legacy",
        source_id=source,
        name="f",
        qualname="f",
        kind="function",
        path="a.py",
        embedding=[0.1, 0.2],
    )
    store.add_symbols([row])
    store.add_symbols([{**row, "name": "f2"}])
    stored = store._native_rows("Symbol", ids=["sym-legacy"])
    assert len(stored) == 1
    assert stored[0].get("generation_id") is None


def test_native_mutation_still_refuses_an_edge_across_two_generations(store):
    gen = generation(store)
    job = claim(store, gen)
    symbol, row = native_fixture(store, gen, job)
    other = generation(store, key="two")
    other_job = claim(store, other, key="job-2")
    other_symbol, other_row = native_fixture(store, other, other_job)
    with pytest.raises(ValueError, match="Native relationship crosses generations"):
        store.link_definitions([(symbol["id"], other_row["id"])])


def test_native_mutation_still_admits_an_edge_to_an_untagged_legacy_row(store):
    source = store.create_source("code", "legacy")
    rows = [
        dict(
            id=f"sym-legacy-{index}",
            source_id=source,
            name="f",
            qualname="f",
            kind="function",
            path=f"a{index}.py",
            embedding=[0.1, 0.2],
        )
        for index in range(2)
    ]
    store.add_symbols(rows)
    store.add_code_edges([{"a": rows[0]["id"], "b": rows[1]["id"], "kind": "INVOKES", "omega": 1.0}])
    assert store._native_rows("Symbol", ids=[rows[0]["id"]])[0].get("generation_id") is None


def test_scoped_relationships_still_see_both_endpoints_of_a_crossing_edge(store):
    """A read narrowed to one generation would hide the far endpoint and lose the guard."""
    gen = generation(store)
    job = claim(store, gen)
    symbol, row = native_fixture(store, gen, job)
    other = generation(store, key="two")
    other_job = claim(store, other, key="job-2")
    other_symbol, other_row = native_fixture(store, other, other_job)
    edges = store._native_relationships(ids={symbol["id"], row["id"]})
    assert any(edge[0] == "DEFINED_IN" for edge in edges)
    # The far generation's rows are not smuggled into this generation's selection.
    flat = {value for edge in edges for value in edge[1:3] if isinstance(value, str)}
    assert other_symbol["id"] not in flat


# --------------------------------------------------------------- bounded work


def test_writing_in_batches_never_does_a_whole_table_native_read(store):
    gen = generation(store)
    job = claim(store, gen)
    with store.generation_write(gen.id, **authority(job)):
        revision, span = evidence(store, gen)
        store.add_passages([passage(gen, revision, span)])
        rows = symbol_rows(store, gen, 24)
        with ReadLog(store) as log:
            for start in range(0, len(rows), 8):
                store.add_symbols(rows[start : start + 8])
    assert log.native_whole_table() == [], "a scoped write must not materialise a whole native table"


def test_batched_writes_do_a_constant_number_of_reads_per_batch(store):
    """O(N/B) scoped reads, not O(N): the per-row reads must be hoisted out of the loop."""
    gen = generation(store)
    job = claim(store, gen)
    counts = {}
    with store.generation_write(gen.id, **authority(job)):
        revision, span = evidence(store, gen)
        store.add_passages([passage(gen, revision, span)])
        for batch in (4, 16):
            rows = symbol_rows(store, gen, batch, start=1000 * batch)
            with ReadLog(store) as log:
                store.add_symbols(rows)
            counts[batch] = len(log.calls)
    assert counts[16] == counts[4], (
        f"reads must be per-batch, not per-row: {counts[4]} reads for 4 rows, {counts[16]} for 16"
    )


def test_native_mutation_reads_only_the_kinds_of_its_argument_ids(store):
    gen = generation(store)
    job = claim(store, gen)
    symbol, row = native_fixture(store, gen, job)
    with store.generation_write(gen.id, **authority(job)), ReadLog(store) as log:
        store.set_symbol_communities({symbol["id"]: 3})
    assert log.native_whole_table() == [], "argument ids bound the membership lookup"
    scoped = [call for call in log.calls if call[0] == "native"]
    assert scoped and all(call[2].get("ids") is not None for call in scoped)


def inject_generation(store, gen, revision, span, count):
    """A generation of `count` symbols written straight into the Fake store's tables.

    The write path has its own tests; this fixture exists to size the seal at the plan's ceiling,
    where going through `add_symbols` would measure batching rather than checksums.
    """
    from hippo.codegraph.model import symbol_id
    from hippo.knowledge.lifecycle import generation_namespace

    workspace = store.get_source(gen.source_id)["workspace_id"]
    namespace = generation_namespace(gen)
    for index in range(count):
        path = f"m{index}.py"
        sid = symbol_id(gen.source_id, path, "f", "function", node_namespace=namespace)
        store.symbols[sid] = dict(
            id=sid,
            source_id=gen.source_id,
            generation_id=gen.id,
            name="f",
            qualname="f",
            kind="function",
            path=path,
            embedding=[0.1, 0.2],
        )
        obj = k.KnowledgeObject(workspace_id=workspace, kind="symbol", canonical_key=f'["{path}","f"]')
        observation = k.ObjectObservation(
            object_id=obj.id,
            revision_id=revision.id,
            span_id=span.id,
            evidence_class="declared",
            recorded_from=NOW,
        )
        for record in (
            obj,
            observation,
            k.GenerationEvidenceMember(
                generation_id=gen.id, record_kind="ObjectObservation", record_id=observation.id
            ),
            k.NativeBinding(
                generation_id=gen.id,
                object_id=obj.id,
                native_kind="Symbol",
                native_id=sid,
                span_id=span.id,
            ),
        ):
            store._knowledge_data.setdefault(type(record).__name__, {})[record.id] = record


def test_sealing_at_the_symbol_ceiling_completes(store):
    """CD1: sealing a generation at the plan's section 8.3 ceiling is linear, not quadratic.

    `CODE_MAX_SYMBOLS_PER_SOURCE` is 50,000. Before this slice the seal read a whole knowledge
    table per row and rescanned the bindings per row, so this fixture did not finish; the
    400-row measurement recorded in `evidence-cc2.md` already cost 1.69 s and grew about
    eightfold per doubling, which is seven more doublings from here.
    """
    if store.knowledge_backend != "fake":
        pytest.skip("the synthetic ceiling fixture is built through the Fake store's tables")
    from hippo.codegraph.model import CODE_MAX_SYMBOLS_PER_SOURCE

    gen = generation(store, key="ceiling")
    job = claim(store, gen, key="job-ceiling")
    with store.generation_write(gen.id, **authority(job)):
        revision, span = evidence(store, gen)
        store.add_passages([passage(gen, revision, span)])
        inject_generation(store, gen, revision, span, CODE_MAX_SYMBOLS_PER_SOURCE)
    start = time.process_time()
    checksums = store.generation_checksums(gen.id)
    elapsed = time.process_time() - start
    assert {c.kind for c in checksums} == {"evidence", "dense", "native"}
    assert next(c for c in checksums if c.kind == "native").row_count == CODE_MAX_SYMBOLS_PER_SOURCE
    # Measured at 3.5 s. The bound is generous because this is a CPU-time assertion on shared
    # hardware; it is three orders of magnitude below what the pre-slice code would have taken.
    assert elapsed < 60, f"sealing {CODE_MAX_SYMBOLS_PER_SOURCE} symbols took {elapsed:.1f}s"


def test_sealing_is_linear_in_the_generation(store):
    """Query scoping does not fix a Python loop that rescans a list per row; CPU is measured too."""
    if store.knowledge_backend != "fake":
        pytest.skip("the synthetic scale fixture is built through the Fake store's tables")

    def elapsed(count, key):
        gen = generation(store, key=key)
        job = claim(store, gen, key=f"job-{key}")
        with store.generation_write(gen.id, **authority(job)):
            revision, span = evidence(store, gen)
            store.add_passages([passage(gen, revision, span)])
            store.add_symbols(symbol_rows(store, gen, count))
            for row in store._native_rows("Symbol", generation_id=gen.id):
                obj = k.KnowledgeObject(
                    workspace_id=store.get_source(gen.source_id)["workspace_id"],
                    kind="symbol",
                    canonical_key=f'["{row["path"]}","f"]',
                )
                store.put_knowledge(obj)
                observation = k.ObjectObservation(
                    object_id=obj.id,
                    revision_id=revision.id,
                    span_id=span.id,
                    evidence_class="declared",
                    recorded_from=NOW,
                )
                store.put_knowledge(observation)
                store.put_knowledge(
                    k.GenerationEvidenceMember(
                        generation_id=gen.id, record_kind="ObjectObservation", record_id=observation.id
                    )
                )
                store.put_knowledge(
                    k.NativeBinding(
                        generation_id=gen.id,
                        object_id=obj.id,
                        native_kind="Symbol",
                        native_id=row["id"],
                        span_id=span.id,
                    )
                )
        start = time.process_time()
        store.generation_checksums(gen.id)
        return time.process_time() - start

    small = elapsed(50, "scale-small")
    large = elapsed(400, "scale-large")
    # Eight times the rows. Linear is ~8x, quadratic is ~64x; 24x leaves room for constants
    # and for the checksum's own sort without admitting a rescan per row.
    assert large < max(small, 0.01) * 24, f"seal is superlinear: {small:.4f}s for 50, {large:.4f}s for 400"


# ------------------------------------------------------------------- schema


def test_native_tables_declare_a_generation_id_index(store):
    """M4: a scoped read on an unindexed property is still a label scan."""
    declared = " ".join(base.CONSTRAINTS)
    for label in ("Symbol", "DataObject", "Commit", "Passage"):
        assert f"FOR (n:{label}) ON (n.generation_id)" in declared


def test_schema_version_six_journals_the_native_generation_indexes(store):
    """`migrate_store` returns early on a current store, so fresh-only declarations never land."""
    assert 5 in migrations.SUPPORTED_CHECKSUMS and 6 in migrations.SUPPORTED_CHECKSUMS
    assert migrations.SUPPORTED_CHECKSUMS[5] != migrations.SUPPORTED_CHECKSUMS[6]
    if store.knowledge_backend == "fake":
        return
    steps = migrations.schema_steps(store, version=6)
    if store.knowledge_backend == "ladybug":
        # Probed on real_ladybug 0.15.3: no secondary-index DDL exists in the dialect.
        assert steps == []
        return
    joined = " ".join(steps)
    for label in ("Symbol", "DataObject", "Commit", "Passage"):
        assert f"FOR (n:{label}) ON (n.generation_id)" in joined


def test_the_frozen_v5_descriptor_is_preserved(store):
    """A v5 store must still validate against the checksum it recorded."""
    assert migrations._descriptor(5)[0] == 5
    assert migrations.SUPPORTED_CHECKSUMS[5] == migrations.V5_CHECKSUM
    assert [*migrations.SUPPORTED_CHECKSUMS] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_a_migrated_store_reports_the_current_version(store):
    store.ensure_schema()
    assert store.schema_version()["version"] == migrations.CURRENT_SCHEMA_VERSION
    assert store.schema_version()["state"] == "complete"
    assert [item["version"] for item in store.schema_history()] == list(range(1, 9))


def test_sealed_generations_still_verify_their_manifest(store):
    gen = generation(store)
    job = claim(store, gen)
    native_fixture(store, gen, job)
    built = manifest(store, gen)
    store.seal_generation(gen.id, built, **authority(job))
    assert {c.kind: c.checksum for c in built.checksums} == {
        c.kind: c.checksum for c in store.generation_checksums(gen.id)
    }

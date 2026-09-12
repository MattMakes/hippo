"""Fenced code-generation writes, resume probing and exact sealing.

The inverse of `staged_prose`: that writer requires the native code and relationship
inventory to be *empty*, which is why the code lane needs its own. Everything else is
the same shape -- a pure batch planner, a callback-free local core, an exact inventory
and a seal -- plus one new algorithm, `probe_staged_rows`, which decides from the
store's own rows which dependency groups a reclaimed generation already holds.

No callback, model call or filesystem access happens inside a transaction, and the
public wrapper refuses an ambient one.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field

from . import model as k
from .access import AuthorizationChanged
from .code_binding import NativeCodeRow
from .code_history import MergedCodeBundle, NativeCommitRow, NativeModifies
from .identity import canonical_json, text_hash

# Plan section 8.3: a code bootstrap is not one transaction, so the prose bootstrap's
# single-transaction ceiling does not apply; this per-batch canonical payload ceiling
# does, in the same unit.
PAYLOAD_CEILING_BYTES = 64 * 1024 * 1024

NATIVE_KINDS = ("Symbol", "DataObject", "Commit")
RELATION_KINDS = ("CODE_EDGE", "DEFINED_IN", "MODIFIES", "PRECEDES")
CODE_EDGE_FIELDS = ("a", "b", "kind", "omega", "provenance", "extra")

# Every refusal that needs operator action names the one exit the plan reserves for it.
CLEANUP = "explicit failed-generation cleanup"


def _vector(values):
    result = tuple(float(value) for value in values)
    if any(value != value or value in (float("inf"), float("-inf")) for value in result):
        raise ValueError("A prepared vector must be finite")
    return result


# ------------------------------------------------------------------ prepared input


@dataclass(frozen=True, slots=True)
class PreparedCodePassage:
    """One bound code or commit passage plus the vector the coordinator produced."""

    passage: object
    embedding: tuple[float, ...]

    def __post_init__(self) -> None:
        if not hasattr(self.passage, "native_row") or not hasattr(self.passage, "chunk"):
            raise ValueError("Expected an immutable bound code or commit passage")
        object.__setattr__(self, "embedding", _vector(self.embedding))
        if not self.embedding:
            raise ValueError("A dense code passage requires a vector")

    @property
    def id(self) -> str:
        return self.passage.id

    def native_row(self) -> dict:
        return {**self.passage.native_row(), "embedding": list(self.embedding)}


@dataclass(frozen=True, slots=True)
class PreparedNativeRow:
    """One `Symbol`, `DataObject` or `Commit` row plus its optional name vector.

    A vector is optional because only symbols and data objects that enter synonym search
    get one (`hipporag.preparation.prepare_code_rows`), and a commit never does.
    """

    row: object
    embedding: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if type(self.row) not in (NativeCodeRow, NativeCommitRow):
            raise ValueError("Expected an immutable bound Symbol, DataObject or Commit row")
        object.__setattr__(self, "embedding", _vector(self.embedding))
        if self.embedding and self.native_kind == "Commit":
            raise ValueError("A commit row carries no vector")

    @property
    def native_kind(self) -> str:
        return self.row.native_kind

    @property
    def native_id(self) -> str:
        return self.row.native_id

    def native_row(self) -> dict:
        row = self.row.row
        return {**row, "embedding": list(self.embedding)} if self.embedding else row


@dataclass(frozen=True, slots=True)
class _CodeEdge:
    """One `add_code_edges` row, carried as canonical JSON so two runs compare equal."""

    row_json: str

    def __post_init__(self) -> None:
        row = json.loads(self.row_json)
        if not isinstance(row, dict) or set(row) != set(CODE_EDGE_FIELDS):
            raise ValueError("A CODE_EDGE row carries exactly the writer's fields")

    @property
    def row(self) -> dict:
        return json.loads(self.row_json)

    @property
    def endpoints(self) -> tuple[str, str]:
        row = self.row
        return row["a"], row["b"]


@dataclass(frozen=True, slots=True)
class _Definition:
    node_id: str
    passage_id: str


@dataclass(frozen=True, slots=True)
class _Precedes:
    newer: str
    older: str


def code_relations(bundle: MergedCodeBundle, facts) -> tuple[tuple[_CodeEdge, ...], tuple[_Definition, ...]]:
    """The `CODE_EDGE` rows and `DEFINED_IN` pairs a bundle plus its graph implies.

    CC6's finding 10: a symbol whose rendered body is only whitespace is skipped by the
    committed chunker, so it sits in `facts.symbols` with no passage and therefore no
    native row. Refusing the build over an empty function body would be wrong, so the
    complement is subtracted here -- an edge with an unbound endpoint is dropped, never
    written, because `native_mutation` would reject it with "Missing shared graph
    endpoint" anyway. A `DEFINED_IN` pair naming an unbound node is dropped for the same
    reason. Pure: no store, no clock, no model.
    """
    if type(bundle) is not MergedCodeBundle:
        raise ValueError("Code relations require the merged code bundle")
    bound = {row.native_id for row in bundle.native_rows}
    edges = []
    for edge in getattr(facts, "edges", ()):
        row = {name: getattr(edge, name) for name in CODE_EDGE_FIELDS}
        if {row["a"], row["b"]} <= bound:
            edges.append(_CodeEdge(canonical_json(row)))
    definitions = []
    for passage in bundle.passages:
        for node in dict.fromkeys(passage.chunk.defines):
            if node in bound:
                definitions.append(_Definition(node, passage.id))
    return tuple(edges), tuple(dict.fromkeys(definitions))


@dataclass(frozen=True, slots=True)
class PreparedCodeIndex:
    """One code generation's complete write plan: evidence, vectors and relations.

    The merged bundle is pure evidence with no vectors, no `CODE_EDGE` rows and no
    `DEFINED_IN` pairs, because CC6 and CC7 hold neither the embedding model nor the
    resolved graph. This type is where the coordinator joins the three, and every
    cross-check that the join is complete happens once, here, outside any transaction.
    """

    bundle: MergedCodeBundle
    dense: tuple[PreparedCodePassage, ...]
    native: tuple[PreparedNativeRow, ...]
    edges: tuple[_CodeEdge, ...] = ()
    definitions: tuple[_Definition, ...] = ()

    def __post_init__(self) -> None:
        if type(self.bundle) is not MergedCodeBundle:
            raise ValueError("The staged code writer takes one merged code bundle")
        for name, kind in (
            ("dense", PreparedCodePassage),
            ("native", PreparedNativeRow),
            ("edges", _CodeEdge),
            ("definitions", _Definition),
        ):
            value = tuple(getattr(self, name))
            object.__setattr__(self, name, value)
            if any(type(item) is not kind for item in value):
                raise ValueError(f"Prepared {name} must be an immutable tuple of {kind.__name__}")
        if tuple(item.passage for item in self.dense) != self.bundle.passages:
            raise ValueError("Dense inventory differs from the bundle's bound passages")
        if tuple(item.row for item in self.native) != self.bundle.native_rows:
            raise ValueError("Native inventory differs from the bundle's bound rows")
        observed = {row.object_id for row in self.bundle.observations}
        if any(item.id not in observed for item in self.bundle.objects):
            raise ValueError("A knowledge object without an observation is unreachable evidence")
        bound = {row.native_id for row in self.native}
        passages = {item.id for item in self.dense}
        for edge in self.edges:
            if not set(edge.endpoints) <= bound:
                raise ValueError("A CODE_EDGE endpoint is outside this generation's native rows")
        for definition in self.definitions:
            if definition.node_id not in bound or definition.passage_id not in passages:
                raise ValueError("A DEFINED_IN pair is outside this generation's rows")
        for name, values in (
            ("CODE_EDGE rows", [edge.endpoints + (edge.row["kind"],) for edge in self.edges]),
            ("DEFINED_IN pairs", list(self.definitions)),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"Duplicate {name}")

    @property
    def generation(self) -> k.Generation:
        return self.bundle.generation

    @property
    def relations(self) -> frozenset[tuple[str, str, str]]:
        """Every `(kind, a, b)` triple this attempt writes into the native representation."""
        return frozenset(
            [
                *(("CODE_EDGE", *edge.endpoints) for edge in self.edges),
                *(("DEFINED_IN", item.node_id, item.passage_id) for item in self.definitions),
                *(("MODIFIES", row.commit_id, row.symbol_id) for row in self.bundle.modifies),
                *(("PRECEDES", newer, older) for newer, older in self.bundle.precedes),
            ]
        )


# ------------------------------------------------------------------ fenced core


def _epochs(store, expected_authorization_epoch, expected_suppression_epoch):
    if (
        type(expected_authorization_epoch) is not int
        or expected_authorization_epoch < 0
        or type(expected_suppression_epoch) is not int
        or expected_suppression_epoch < 0
        or store.authorization_epoch() != expected_authorization_epoch
        or store.suppression_epoch() != expected_suppression_epoch
    ):
        raise AuthorizationChanged("Authorization or suppression epoch changed during staged writing")


@contextmanager
def _local(
    store,
    prepared,
    *,
    job_id,
    lease_owner,
    fencing_token,
    expected_authorization_epoch,
    expected_suppression_epoch,
):
    credentials = dict(job_id=job_id, lease_owner=lease_owner, fencing_token=fencing_token)
    gen = prepared.generation
    # generation_write takes the authorization lock before the source lock.
    with store.generation_write(gen.id, **credentials):
        _epochs(store, expected_authorization_epoch, expected_suppression_epoch)
        current = store._generation(gen.id)
        if current.replace(coverage_json=gen.coverage_json) != gen:
            raise ValueError("Persisted generation differs from accepted preparation")
        yield
        _epochs(store, expected_authorization_epoch, expected_suppression_epoch)
        store._check_build(gen.id, **credentials, states=("staging", "ready"))


def _accepted(store, prepared):
    from .generation_profiles import embedding_mode, validate_generation_profile

    generation = store._generation(prepared.generation.id)
    if embedding_mode(generation) != "verified_v1":
        raise ValueError("Managed code writer requires a controlled verified profile binding")
    bound = validate_generation_profile(store, generation)
    if (bound.profile.fingerprint, bound.config_fingerprint) != (
        prepared.generation.embedding_profile,
        text_hash(prepared.bundle.configuration_json),
    ):
        raise ValueError("Bound profile/configuration differs from prepared inputs")
    for artifact, revision in (*prepared.bundle.accepted_pairs, *prepared.bundle.history_pairs):
        for record in (artifact, revision):
            if store._knowledge_get(type(record).__name__, record.id) != record:
                raise ValueError("Persisted accepted artifact/revision inventory differs")


# ------------------------------------------------------------------ batch planning


@dataclass(frozen=True, slots=True)
class _Group:
    """One complete dependency group: what to write, and how to recognise it again."""

    records: tuple
    probes: tuple = ()
    shared: tuple = field(default=())


def _groups(prepared):
    """Every dependency group, in the plan's order. Pure and deterministic.

    The plan's order is accepted preflight, revision members, objects, original spans,
    derived views, dense passages, native rows and bindings, native relations, history.
    Two deviations, both forced and both tested:

    * `ObjectObservation`s are not in the plan's list at all, yet every observation cites
      a span, so the objects stage moves *after* the spans stage and each object travels
      with its own observations. That also makes the group recognisable from one scoped
      read -- an observation carries a `GenerationEvidenceMember`, a `KnowledgeObject`
      carries nothing generation-scoped at all.
    * A `NativeBinding` is written in the same group as the native row it binds, because
      `put_knowledge` dereferences the row (`store/knowledge.py:696`).
    """
    bundle = prepared.bundle
    gen_id = bundle.generation.id

    def selected(record):
        return (
            record,
            k.GenerationEvidenceMember(
                generation_id=gen_id, record_kind=type(record).__name__, record_id=record.id
            ),
        )

    def exact(record):
        return ("exact", (type(record).__name__, record.id), record)

    yield _Group((None,))  # Accepted inventory preflight, before any mutation.
    for member in bundle.revision_members:
        yield _Group((member,), (("member", member.id, member),))
    observations = {}
    for row in bundle.observations:
        observations.setdefault(row.object_id, []).append(row)
    for span in bundle.spans:
        yield _Group(selected(span), (exact(span),))
    for item in bundle.objects:
        rows = observations[item.id]
        records = [item]
        for row in rows:
            records.extend(selected(row))
        yield _Group(tuple(records), tuple(exact(row) for row in rows), (("KnowledgeObject", item),))
    dependencies = {}
    for edge in bundle.derived_dependencies:
        dependencies.setdefault(edge.derived_record_id, []).append(edge)
    derived = {record.id: record for record in bundle.derived_records}
    for view in bundle.views:
        records = list(selected(derived[view.derived_record_id]))
        for edge in dependencies[view.derived_record_id]:
            records.extend(selected(edge))
        records.extend(selected(view))
        yield _Group(tuple(records), tuple(exact(record) for record in records[::2]))
    for item in prepared.dense:
        yield _Group((item,), (("native", ("Passage", item.id), item.native_row()),))
    bindings = {(binding.native_kind, binding.native_id): binding for binding in bundle.bindings}
    for item in prepared.native:
        binding = bindings[(item.native_kind, item.native_id)]
        yield _Group(
            (item, binding),
            (
                ("native", (item.native_kind, item.native_id), item.native_row()),
                ("binding", binding.id, binding),
            ),
        )
    for edge in prepared.edges:
        yield _Group((edge,), (("relation", ("CODE_EDGE", *edge.endpoints), None),))
    for item in prepared.definitions:
        yield _Group((item,), (("relation", ("DEFINED_IN", item.node_id, item.passage_id), None),))
    for row in bundle.modifies:
        yield _Group((row,), (("relation", ("MODIFIES", row.commit_id, row.symbol_id), None),))
    for newer, older in bundle.precedes:
        yield _Group((_Precedes(newer, older),), (("relation", ("PRECEDES", newer, older), None),))


def _payload(record):
    if record is None:
        return None
    if isinstance(record, k.Record):
        return record.model_dump(mode="json")
    if type(record) is PreparedCodePassage:
        return record.native_row()
    if type(record) is PreparedNativeRow:
        return record.native_row()
    if type(record) is _CodeEdge:
        return record.row
    if type(record) is _Definition:
        return [record.node_id, record.passage_id]
    if type(record) is NativeModifies:
        return record.row
    return [record.newer, record.older]


def _write_batches(prepared, *, batch_size, resume=None):
    """Yield complete dependency groups; no store, callback or model is retained."""
    if type(prepared) is not PreparedCodeIndex or type(batch_size) is not int or batch_size < 1:
        raise ValueError("Expected immutable prepared output and positive batch size")
    skipped = ()
    if resume is not None:
        if type(resume) is not ResumePlan or resume.generation_id != prepared.generation.id:
            raise ValueError("A resume plan belongs to the generation it was probed against")
        skipped = resume.skipped
    batch, count, index = [], 0, 0
    for group in _groups(prepared):
        if index in skipped:
            index += 1
            continue
        index += 1
        batch.extend(group.records)
        count += 1
        if count == batch_size:
            yield tuple(batch)
            batch, count = [], 0
    if resume is not None and index != resume.group_count:
        raise ValueError("A resume plan belongs to the preparation it was probed against")
    if batch:
        yield tuple(batch)


def _check_ceiling(batch):
    """Refuse an oversized batch before its transaction opens (plan section 8.3)."""
    size = len(canonical_json([_payload(record) for record in batch]).encode("utf-8"))
    if size > PAYLOAD_CEILING_BYTES:
        raise ValueError(f"Staged code batch payload is {size} bytes; the ceiling is {PAYLOAD_CEILING_BYTES}")


def _immutable_native(store, kind, rows):
    """A persisted row whose canonical payload differs is never overwritten.

    `native_write` treats rows differing only in `boost`, `community`, `entities_json`,
    `triples_json` or `extraction_error` as identical and skips them, so relying on it
    would accept a row this attempt did not compute (design review question 4). The
    canonical payload itself is compared instead.
    """
    wanted = {row["id"]: row for row in rows}
    for existing in store._native_rows(kind, ids=list(wanted)):
        if store._canonical_native(kind, existing) != store._canonical_native(kind, wanted[existing["id"]]):
            raise ValueError(f"Conflicting staged {kind} row; {CLEANUP} required")


def _write_batch(store, prepared, batch, **authority):
    """Callback-free local core; safe under an existing outer transaction."""
    _check_ceiling(batch)
    with _local(store, prepared, **authority):
        records, bindings = [], []
        dense, native = [], {}
        edges, definitions, modifies, precedes = [], [], [], []
        for record in batch:
            if record is None:
                _accepted(store, prepared)
            elif type(record) is PreparedCodePassage:
                dense.append(record)
            elif type(record) is PreparedNativeRow:
                native.setdefault(record.native_kind, []).append(record)
            elif type(record) is _CodeEdge:
                edges.append(record.row)
            elif type(record) is _Definition:
                definitions.append((record.node_id, record.passage_id))
            elif type(record) is NativeModifies:
                modifies.append(record.row)
            elif type(record) is _Precedes:
                precedes.append((record.newer, record.older))
            elif type(record) is k.NativeBinding:
                bindings.append(record)
            else:
                records.append(record)
        # Dependency order inside one batch: evidence, dense rows, native rows, then the
        # bindings that dereference them, then every relation over those endpoints.
        for record in records:
            store.put_knowledge(record)
        if dense:
            rows = [item.native_row() for item in dense]
            _immutable_native(store, "Passage", rows)
            store.add_passages(rows)
        for kind, writer in (
            ("Symbol", "add_symbols"),
            ("DataObject", "add_data_objects"),
            ("Commit", "add_commits"),
        ):
            if kind in native:
                rows = [item.native_row() for item in native[kind]]
                _immutable_native(store, kind, rows)
                getattr(store, writer)(rows)
        for record in bindings:
            store.put_knowledge(record)
        if edges:
            store.add_code_edges(edges)
        if definitions:
            store.link_definitions(definitions)
        if modifies:
            store.add_modifies(modifies)
        if precedes:
            store.add_precedes(precedes)


# ------------------------------------------------------------------ resume probe


@dataclass(frozen=True, slots=True)
class ResumePlan:
    """Which dependency groups a reclaimed generation already holds."""

    generation_id: str
    group_count: int
    skipped: frozenset[int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "skipped", frozenset(self.skipped))
        if any(index not in range(self.group_count) for index in self.skipped):
            raise ValueError("A resume plan names a group the preparation does not have")

    @property
    def skipped_groups(self) -> int:
        """What `BuildReceipt.resumed_from_batches` reports."""
        return len(self.skipped)


def _persisted(store, prepared):
    """Every generation-scoped row the store already holds, one scoped read per kind."""
    gen_id = prepared.generation.id
    rows = {
        "member": {row.id: row for row in store._knowledge_rows("GenerationMember", generation_id=gen_id)},
        "binding": {row.id: row for row in store._knowledge_rows("NativeBinding", generation_id=gen_id)},
        "exact": {
            (row.record_kind, row.record_id): row
            for row in store._knowledge_rows("GenerationEvidenceMember", generation_id=gen_id)
        },
        "native": {
            (kind, row["id"]): row
            for kind in ("Passage", *NATIVE_KINDS)
            for row in store._native_rows(kind, generation_id=gen_id)
        },
    }
    rows["relation"] = {
        (entry[0], entry[1], entry[2]): entry
        for entry in store._native_relationships(generation_id=gen_id)
        if entry[0] != "shared"
    }
    return rows


def probe_staged_rows(store, prepared) -> ResumePlan:
    """Decide, per dependency group, whether a reclaimed generation already holds it.

    Three outcomes and nothing else. SKIP when every row of the group is present and its
    payload equals what this attempt would write. WRITE when none of them is present.
    FAIL CLOSED -- a `ValueError` naming the explicit failed-generation cleanup path --
    when a group is partially present, when a present payload differs, or when the store
    holds any generation-scoped row this attempt would not produce.

    The absence half is design review M2: most evidence IDs are content-derived, so a
    record written by a different derivation is an extra orphan row rather than a
    conflicting one, and a probe that only looked for what it expects would never see it.

    Payloads are compared through `_canonical_native` for native rows and by record
    equality for knowledge rows -- never a sample, and never `native_write`'s tolerant
    equality, which ignores exactly the columns a different attempt would change.
    """
    if type(prepared) is not PreparedCodeIndex:
        raise ValueError("A resume probe takes the immutable prepared code output")
    persisted = _persisted(store, prepared)
    groups = list(_groups(prepared))
    expected = {flavour: set() for flavour in persisted}
    for group in groups:
        for flavour, key, _ in group.probes:
            expected[flavour].add(key)
    for flavour, actual in persisted.items():
        extra = set(actual) - expected[flavour]
        if extra:
            raise ValueError(
                f"The staged generation holds {len(extra)} {flavour} rows this build would not "
                f"produce; {CLEANUP} required"
            )
    skipped = set()
    for index, group in enumerate(groups):
        if not group.probes:
            continue  # The accepted preflight is a read, never a write, and never skipped.
        present = []
        for flavour, key, record in group.probes:
            stored = persisted[flavour].get(key)
            if stored is None:
                present.append(False)
                continue
            if flavour == "native":
                kind = key[0]
                if store._canonical_native(kind, stored) != store._canonical_native(kind, record):
                    raise ValueError(f"A staged {kind} row differs from this build; {CLEANUP} required")
            elif flavour in ("member", "binding") and stored != record:
                raise ValueError(f"A staged {flavour} record differs from this build; {CLEANUP} required")
            present.append(True)
        if not any(present):
            continue
        if not all(present):
            raise ValueError(f"A staged dependency group is incomplete; {CLEANUP} required")
        for flavour, key, record in group.probes:
            if flavour == "exact" and store._knowledge_get(key[0], key[1]) != record:
                raise ValueError(f"A staged {key[0]} payload differs from this build; {CLEANUP} required")
        for kind, record in group.shared:
            if store._knowledge_get(kind, record.id) != record:
                raise ValueError(f"A staged {kind} payload differs from this build; {CLEANUP} required")
        skipped.add(index)
    return ResumePlan(prepared.generation.id, len(groups), frozenset(skipped))


# ------------------------------------------------------------------ inventory and seal


def _inventory(store, prepared):
    """The inverse of the prose inventory: the exact native code inventory must be here."""
    _accepted(store, prepared)
    bundle = prepared.bundle
    gen_id = bundle.generation.id

    def selected(kind):
        return {r.id: r for r in store._knowledge_rows(kind, generation_id=gen_id)}

    for kind, expected in (
        ("GenerationMember", bundle.revision_members),
        ("GenerationEvidenceMember", bundle.evidence_members),
        ("NativeBinding", bundle.bindings),
    ):
        if selected(kind) != {r.id: r for r in expected}:
            raise ValueError(f"Exact {kind} inventory differs from prepared coverage")
    for record in (*bundle.objects, *bundle.records):
        if store._knowledge_get(type(record).__name__, record.id) != record:
            raise ValueError("Persisted evidence payload differs from prepared inventory")
    for kind, expected in (
        ("Passage", {item.id: item.native_row() for item in prepared.dense}),
        *(
            (
                kind,
                {item.native_id: item.native_row() for item in prepared.native if item.native_kind == kind},
            )
            for kind in NATIVE_KINDS
        ),
    ):
        actual = {
            row["id"]: store._canonical_native(kind, row)
            for row in store._native_rows(kind, generation_id=gen_id)
        }
        if actual != {key: store._canonical_native(kind, row) for key, row in expected.items()}:
            raise ValueError(f"Native {kind} inventory differs from prepared coverage")
    actual = {
        (entry[0], entry[1], entry[2])
        for entry in store._native_relationships(generation_id=gen_id)
        if entry[0] != "shared"
    }
    if actual != prepared.relations:
        raise ValueError("Native relationship inventory differs from prepared coverage")
    if selected("ProseExtraction"):
        raise ValueError("A code generation produces no prose extraction")


def _seal(store, prepared, **authority):
    """Compare and seal inside one local transaction; never invoke callbacks."""
    with _local(store, prepared, **authority):
        _inventory(store, prepared)
        bundle = prepared.bundle
        manifest = k.IndexManifest(
            generation_id=bundle.generation.id,
            profile_fingerprint=bundle.generation.embedding_profile,
            config_fingerprint=text_hash(bundle.configuration_json),
            required_representations=("evidence", "dense", "native"),
            checksums=store.generation_checksums(bundle.generation.id),
            ready=True,
        )
        store.seal_generation(
            bundle.generation.id,
            manifest,
            **{key: authority[key] for key in ("job_id", "lease_owner", "fencing_token")},
        )
        return manifest


def write_staged_code(
    store,
    prepared,
    *,
    job_id,
    lease_owner,
    fencing_token,
    expected_authorization_epoch,
    expected_suppression_epoch,
    check,
    batch_size=128,
    resume=None,
):
    """Write/seal one code generation outside ambient transactions; caller publishes."""
    if store.in_ambient_transaction():
        raise ValueError("Staged code wrapper requires no outer transaction")
    if type(prepared) is not PreparedCodeIndex or not callable(check):
        raise ValueError("Prepared output and live build check are required")
    authority = dict(
        job_id=job_id,
        lease_owner=lease_owner,
        fencing_token=fencing_token,
        expected_authorization_epoch=expected_authorization_epoch,
        expected_suppression_epoch=expected_suppression_epoch,
    )
    for batch in _write_batches(prepared, batch_size=batch_size, resume=resume):
        check()
        _write_batch(store, prepared, batch, **authority)
        check()
    check()
    manifest = _seal(store, prepared, **authority)
    check()
    return manifest

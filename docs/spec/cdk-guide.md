# Writing a hippo connector

A connector teaches hippo about one kind of provider: a ticket tracker, a wiki, a catalogue, a
directory of exported files. You write a descriptor, a little vocabulary and five methods. hippo
does the rest — fetching on a schedule, hashing and storing raw bytes, publishing a generation,
answering questions with citations that resolve back to your spans.

This guide walks the worked example the test suite itself uses,
`tests/fakes/fixture_connector/`. Every Python block below is that package's source, checked
against it by `tests/unit/test_connector_scaffold.py`, so nothing here can drift from code that
runs.

## 1. What a connector is

A connector is two halves, and the split is the whole design.

**The provider half** — `probe`, `list_changes`, `fetch`, `fetch_policy` — talks to the outside
world. It may call the network, read the clock, and resolve a credential reference. It returns
bytes and the provider's own metadata, unchanged.

**`emit` is pure.** Bytes in, records out. No network, no model, no store, no clock. The runtime
runs it inside a guard that refuses all four, so two runs over the same revision produce
byte-identical output and a rebuild can be trusted rather than re-checked.

What a connector never touches:

| Not yours | Why |
| --- | --- |
| The store | The runtime writes. You return records; it decides what is new. |
| The index and the embeddings | Derived from what you emit, on hippo's schedule. |
| The model | A connector never asks a language model anything. Rules, not guesses. |
| The clock, inside `emit` | An ingestion timestamp in a record makes every rebuild differ. |
| The evidence class | Derived from the family, the source and the metadata origin. You cannot set it. |

## 2. `hippo connector new`

```text
hippo connector new incidents_ndjson --family incident --kinds incident
```

That writes a package that already passes the kit, so you start from green and edit toward your
provider rather than toward a first passing test:

| File | What it holds |
| --- | --- |
| `__init__.py` | `from .connector import IncidentsNdjsonConnector as Connector` — the name hippo resolves |
| `connector.py` | The descriptor, the configuration model, and the five methods |
| `types.py` | The `TypeExtension`: your object kinds, and the connector kind itself |
| `templates.py` | The `FactTemplate` objects your kinds render |
| `fixtures/basic/config.json` | One instance's configuration, as the kit will replay it |
| `fixtures/basic/changes.json` | The pages `list_changes` would have returned |
| `fixtures/basic/policies.json` | What `fetch_policy` would have answered, per record |
| `fixtures/basic/inputs/<id>` | The bytes `fetch` would have returned, one file per record |
| `fixtures/basic/expected/*.json` | The seven goldens: what publishing this case produces |
| `fixtures/registry.lock.json` | A hash per registered name, so a silent vocabulary change is caught |
| `tests/test_connector.py` | `assert validate_package(...).passed` |

`--dest` chooses where the package lands. `--family` must be a family hippo already knows
(`change`, `code`, `custom`, `db`, `incident`, `prose`, `service`, `work`); `custom` is the
default and is the right answer when nothing else fits. The package name is also its connector
kind and its descriptor name: hippo refuses a package where those three disagree, so rename all
three together or none.

## 3. The descriptor

The descriptor is what your connector claims about itself. It is read before any provider call, so
everything hippo needs in order to decide whether to run you is here.

<!-- cdk-guide: example descriptor -->
```python
DESCRIPTOR = base.ConnectorDescriptor(
    name=FIXTURE_CONNECTOR_KIND,
    version="1",
    families=(FIXTURE_FAMILY,),
    kinds=(FIXTURE_NOTE_KIND,),
    predicates=(FIXTURE_LINKS,),
    artifact_kinds=("document",),
    locator_kinds=("field",),
    capabilities=base.ConnectorCapabilities(changes_feed=True, deletion_feed=True, acls=True, inventory=True),
    config_model=FixtureConfig,
    credentials=(base.CredentialRequirement(name="fixture_token"),),
    parsers=(),
    extension=FIXTURE_EXTENSION,
)
```

`families` is what this connector writes about; `kinds` and `predicates` are the names it emits.
`capabilities` is a set of promises the runtime acts on, and `inventory=True` is the heaviest of
them: it says a walk from no cursor sees the whole partition, which is what lets hippo delete what
a completed walk did not return. Promise it only when it is true.

`credentials` names references, never values. A configuration field whose name contains
`credential` is refused outright, so a secret cannot be typed into an instance's configuration by
accident.

`extension` is the vocabulary of the next section. Carrying it on the descriptor is what lets
`hippo connector validate` register your types into a scratch registry without installing anything.

## 4. Registering types

Object kinds, their attributes, their fact templates and the predicates between them:

<!-- cdk-guide: example types -->
```python
class FixtureNoteAttributes(BaseModel):
    """A note's typed attributes; `extra="forbid"` is required of every extension kind (S1 D5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    updated: str | None = None


def fixture_note_kind(**overrides) -> ObjectKindDefinition:
    fields = {
        "name": FIXTURE_NOTE_KIND,
        "family": FIXTURE_FAMILY,
        # `instance` is filled by the kit's key builder and never emitted (S4 scaffold note).
        "key_template": ("instance", "note_id"),
        "key_prefix": "note",
        "attrs_model": FixtureNoteAttributes,
        "label_template": "{title}",
        "fact_templates": (
            FactTemplate(
                name="note_summary",
                version="1",
                consumes=("title", "updated"),
                text="Note {key} titled {title} was updated {updated}",
            ),
        ),
    }
    return ObjectKindDefinition(**(fields | overrides))


def fixture_links_predicate(**overrides) -> PredicateDefinition:
    fields = {
        "name": FIXTURE_LINKS,
        "subject_kinds": frozenset({FIXTURE_NOTE_KIND}),
        "object_kinds": frozenset({FIXTURE_NOTE_KIND}),
        "owner_families": frozenset({FIXTURE_FAMILY}),
        "canonical_direction": "subject_to_object",
        "family_default": "deterministic",
        "sources_allowed": frozenset({"metadata"}),
        "verb_phrase": "links to",
    }
    return PredicateDefinition(**(fields | overrides))


def fixture_extension(**overrides) -> TypeExtension:
    fields = {
        "object_kinds": (fixture_note_kind(),),
        "predicates": (fixture_links_predicate(),),
        "connector_kinds": (FIXTURE_CONNECTOR_KIND,),
    }
    return TypeExtension(**(fields | overrides))


FIXTURE_EXTENSION = fixture_extension()
```

Four things here are worth reading twice.

**`key_template` starts with `instance`, and you never emit it.** hippo fills the instance from the
connector row, so note `n1` on one server and note `n1` on another stay two objects. Your `emit`
supplies the parts your bytes can see and nothing more.

**`attrs_model` forbids extra fields.** An attribute nobody declared is a mapping mistake, not a
free-form field, and it is refused where it happens rather than discovered in a query.

**A fact template is a sentence hippo can re-derive.** Every field in `text` must be named in
`consumes`; `{key}` is the object's own key. One template renders one unit per object. Change the
text and the version together — the registry lock pins `name@version`, and text that moved under
an unmoved version is a contract violation.

**A predicate names its owner families.** Only a connector writing for an owner family may emit
that edge, and only in the declared direction. `support_required` means an edge without an
evidence span is refused: a relation nobody can point at is a guess.

## 5. Talking to the provider

<!-- cdk-guide: example sync_half -->
```python
class FixtureConnector:
    def probe(self, config: BaseModel, clock) -> base.Classification:
        """Sample through this connector's own `list_changes` and `fetch` (ruling R60)."""
        items, cursor = [], None
        while len(items) < PROBE_SAMPLE:
            page = self.list_changes(config, cursor)
            for change in page.changes:
                if change.operation != "upsert" or len(items) >= PROBE_SAMPLE:
                    continue
                fetched = self.fetch(config, change.ref)
                items.append(
                    classify.SampledItem(
                        partition=change.ref.partition,
                        path=change.ref.external_id,
                        data=fetched.data,
                        provider_type="note",
                    )
                )
            cursor = page.next_cursor
            if page.complete or cursor is None:
                break
        return classify.classify(
            self.descriptor,
            config,
            items,
            current_registry(),
            spec=classify.classifier_spec(),
            capabilities=self.descriptor.capabilities,
            kinds=(base.KindMapping(provider_type="note", kind=FIXTURE_NOTE_KIND),),
        )

    def list_changes(self, config: BaseModel, cursor: base.SyncCursor | None) -> base.ChangePage:
        page = 0 if cursor is None else int(json.loads(cursor.value)["page"])
        scan = "inventory" if cursor is None else cursor.scan
        body, _headers = self.client.get_bytes(
            f"api/partitions/{quote(config.partition, safe='')}/changes",
            params={"page": str(page), "scan": scan},
        )
        # The contract models are strict, so the page is validated from JSON, never from a dict.
        return base.ChangePage.model_validate_json(body)

    def fetch(self, config: BaseModel, ref: base.ExternalRef) -> base.RawFetch:
        data, _headers = self.client.get_bytes(f"api/notes/{quote(ref.external_id, safe='')}")
        note = json.loads(data.decode("utf-8"))
        return base.RawFetch(
            ref=ref,
            data=data,
            content_type="application/json",
            external_id=ref.external_id,
            canonical_uri=note["url"],
            provider_revision=note.get("updated"),
            source_updated_at=_instant(note.get("updated")),
            source_timestamp_original=note.get("updated"),
            source_timezone="UTC",
            source_precision="second",
        )

    def fetch_policy(self, config: BaseModel, ref: base.ExternalRef) -> base.PolicyObservation:
        body, _headers = self.client.get_bytes(f"api/notes/{quote(ref.external_id, safe='')}/acl")
        payload = json.loads(body.decode("utf-8")) | {"ref": ref.model_dump(mode="json")}
        return base.PolicyObservation.model_validate_json(json.dumps(payload))
```

`list_changes` returns one page at a time. A page names one partition and carries a cursor for the
next; `complete=True` on the last page of a walk that saw everything is the promise `inventory`
made. Return changes with `operation="delete"` when the provider tells you something is gone.

`fetch` returns the provider's bytes unchanged. Hash-and-store happens downstream, so a
normalisation here would make a rebuild differ from the first build. `canonical_uri` is stored and
shown to readers, so it must never carry a token or any other secret in its query string — the kit
checks.

`fetch_policy` answers who may read one record. When the provider cannot say, return
`state="unknown"`: hippo stores that as deny. An unknown observation carries no principals at all,
which is why the model refuses to build one that does.

`probe` samples through this connector's own `list_changes` and `fetch` rather than through a
private path. That is what lets the kit replay a probe exactly, and it means a probe costs you no
extra code. It must be a pure function of the descriptor, the configuration and the sampled bytes:
run it twice against two different clock readings and the two `Classification` values must be
equal.

The `transport=` argument is how the fixture connector reaches a canned provider rather than the
network. The kit re-exports `record_transport` and `replay_transport` for the same purpose in your
own tests: record once against a real instance, commit the recording, replay it afterwards.

## 6. `emit`

<!-- cdk-guide: example emit -->
```python
class FixtureConnector:
    def emit(self, revision: base.RevisionInput, mapping: base.TypeMapping) -> base.EmissionBatch:
        note = json.loads(revision.data.decode("utf-8"))
        if "body" not in note:
            return base.EmissionBatch(
                failures=(base.ParseFailure(family=FIXTURE_FAMILY, reason="missing_body"),)
            )
        ref = _note_ref(note["id"])
        nodes = [
            base.NodeEmission(
                ref=ref,
                attrs={"title": note["title"], "updated": note.get("updated")},
                span=_field_span("title", note["title"]),
                source="metadata",
                metadata_origin="catalog",
                ts=_instant(note.get("updated")),
                ts_original=note.get("updated"),
                ts_timezone="UTC",
                ts_precision="second",
            )
        ]
        body = note["body"]
        passages = [base.PassageEmission(key="body", span=_field_span("body", body), title=note["title"])]
        units = [
            base.UnitEmission(
                key=f"sentence-{ordinal}",
                passage="body",
                ordinal=ordinal,
                kind="sentence",
                span=_field_span("body", body),
                start=start,
                end=end,
            )
            for ordinal, (start, end) in enumerate(_sentences(body))
        ]
        edges, aliases = [], []
        for index, target in enumerate(note.get("links", ())):
            path = f"links.{index}"
            nodes.append(self._endpoint(target, path))
            edges.append(
                base.EdgeEmission(
                    subject=ref,
                    predicate=FIXTURE_LINKS,
                    object=_note_ref(target),
                    family="deterministic",
                    source="metadata",
                    metadata_origin="catalog",
                    weight=1.0,
                    support=(base.SupportEmission(spans=(_field_span(path, target),)),),
                )
            )
        for index, target in enumerate(note.get("same_as", ())):
            path = f"same_as.{index}"
            nodes.append(self._endpoint(target, path))
            aliases.append(
                base.AliasEmission(
                    a=ref,
                    b=_note_ref(target),
                    rule="explicit_annotation",
                    support=(base.SupportEmission(spans=(_field_span(path, target),)),),
                )
            )
        return base.EmissionBatch(
            nodes=tuple(nodes),
            edges=tuple(edges),
            passages=tuple(passages),
            units=tuple(units),
            aliases=tuple(aliases),
        )

    @staticmethod
    def _endpoint(target: str, path: str) -> base.NodeEmission:
        """An endpoint this revision only names: its title is the id it was linked by.

        `updated` is absent, so `note_summary` renders nothing for it and the omission is counted
        rather than guessed (S6 R-S2-5).
        """
        return base.NodeEmission(
            ref=_note_ref(target),
            attrs={"title": target},
            span=_field_span(path, target),
            source="metadata",
            metadata_origin="catalog",
        )
```

An `EmissionBatch` holds five things, and every one of them is optional:

- **nodes** — an object this revision describes, with its typed attributes and the span they were
  read from. A node for an endpoint you only *name* carries the id as its title; hippo counts what
  it could not render rather than inventing it.
- **edges** — a registered predicate between two node references, with the support spans that
  earn it. Only an owner family may write one, only in the canonical direction.
- **passages** — verbatim text a reader should see. Rendered passages come from your fact
  templates; you emit only what the provider actually wrote.
- **units** — the slices of a passage that get embedded. Offsets are into the passage's own text.
- **aliases** — two references that name one thing, each with the rule that decided it. The rule
  is a name, not a sentence: a future reader must be able to ask why.

A record you cannot read becomes a counted `ParseFailure`, never an exception. One unreadable
record must not fail a partition, and a failure nobody counted is a silent gap in the memory.

Things that will fail validation, and are worth checking before you run it:

- reading `time`, `httpx`, the store or a model anywhere `emit` can reach;
- a span whose `text` is not what the revision bytes hold at that locator;
- a node timestamp that is the moment of ingestion rather than the provider's own;
- a key part your kind never declared, or a kind nothing registered.

## 7. Fixtures and goldens

A case is a directory under `fixtures/`. Its name becomes part of an operation id, so keep it
short and lower case.

| Path | What it is |
| --- | --- |
| `config.json` | The instance configuration this case runs under |
| `changes.json` | `{"pages": [...]}`, one `ChangePage` per page, plus an optional `fetches` map of per-record `RawFetch` metadata |
| `policies.json` | One `PolicyObservation` per external id, or a list of them to replay a policy that changes |
| `inputs/<external_id>` | The exact bytes `fetch` returns. An id with no file replays as "not found", which is how a deletion is confirmed |
| `http/` | Recorded HTTP exchanges, when your own tests use `record_transport` |
| `expected/` | The seven goldens |

The goldens are `nodes.json`, `edges.json`, `passages.json`, `units.json`, `aliases.json`,
`failures.json` and `coverage.json`. They are canonical JSON, sorted by id, with run-local
identifiers replaced by stable tokens (`<source>`, `<generation>`, `<passage-0>`) so the same case
produces the same bytes on every backend and in every run.

```text
hippo connector validate . --update-golden
```

rewrites them and prints the diff. Read the diff before you commit it: that is the whole point of
a golden. A change you cannot explain in one sentence is a bug you have just blessed.

## 8. `hippo connector validate`

```text
hippo connector validate ./incidents_ndjson
```

Exit `0` means every rule below passed and no golden moved. Exit `1` names what broke. Exit `2`
means the package could not be loaded, is not trusted, or its vocabulary was refused.

Each rule fires on its own condition and skips what another rule owns, so you get one name and one
line rather than a cascade.

| Rule | It fires when | Fix it by |
| --- | --- | --- |
| `registered_vocabulary` | A reference names a kind, predicate or locator kind nothing registered | Declaring it in `types.py`, or correcting the name |
| `nodes_have_locator_and_policy` | A node emission carries no span | Pointing every node at the field it was read from |
| `unknown_policy_is_deny` | An unknown policy observation reaches a stored policy as anything but deny, or carries allowed principals | Returning `state="unknown"` with no principals, and letting hippo decide |
| `edges_fully_attributed` | An edge's family, source and metadata origin have no row in the derivation table | Choosing a combination the table defines; you cannot set an evidence class directly |
| `aliases_name_a_rule` | An alias emission names no rule | Naming the rule that decided it, as a code |
| `no_ingestion_time` | A record's timestamp is the moment hippo read it | Emitting the provider's own timestamp, or none |
| `one_fact_per_unit` | A rendered unit is not one template's output over its own passage | Letting the fact templates render, rather than composing text in `emit` |
| `spans_match_bytes` | A span's text is not what the revision holds at its locator | Quoting the bytes, or fixing the locator |
| `passages_within_token_bound` | A passage is longer than the bound a retrievable passage may be | Splitting it where the provider splits it |
| `identities_from_builders` | A reference's key has a part its kind never declared | Matching `key_template`, minus the instance parts hippo fills |
| `direction_and_ownership` | An edge runs backwards, or a family that does not own the predicate wrote it | Emitting it from the owner, in the canonical direction |
| `parse_failures_counted` | A revision produced nothing and reported no failure | Returning a `ParseFailure` whenever you give up on a record |
| `emit_deterministic` | Two calls over one revision differ | Removing the ordering, the set iteration or the random source behind it |
| `emit_pure` | `emit` reached the clock, the network, a model or the store | Moving that call into the provider half |
| `change_page_single_partition` | A page carries a change belonging to another partition | Paging per partition |
| `fetch_matches_ref` | `fetch` answered with a different record than the one asked for | Returning the requested id, and raising "not found" when it is gone |
| `canonical_uri_without_credentials` | A canonical URI carries a token or other secret | Building the URI a reader would use |
| `unknown_policy_carries_no_principals` | An unknown observation names allowed or denied principals | Reporting `state="known"` when you actually know |
| `probe_deterministic` | Two probes under two clock readings disagree | Removing the clock, the sampling order or the network call behind it |
| `registry_version_bump` | A registered name's definition changed under an unmoved version | Bumping the version in the same edit that changes the text |

Five more rules run the whole runtime against your case and fail it on a durability defect rather
than a contract one:

| Scenario | What it proves |
| --- | --- |
| `crash_after_fetch` | A failure between fetching and checkpointing leaves the last published generation intact and commits no checkpoint |
| `replayed_page` | Replaying a page changes nothing: no new generation, no moved policy epoch |
| `failed_inventory` | A walk that failed part way deletes nothing, because it never completed |
| `policy_change_mid_page` | A policy that narrows mid-page takes effect at the checkpoint, and every stored span keeps a policy |
| `delete_with_live_session` | Deleting a record while a query session is open leaves that session able to finish |

`emit_deterministic` and `emit_pure` also run on their own, twice per revision, before anything is
published.

## 9. `hippo connector probe` and classification

```text
hippo connector probe incidents_ndjson --config ./instance.json
```

A probe reads a sample and says what it found: the family, the mapping from provider type to
object kind, the capabilities it observed, and any warnings. It writes nothing, opens no database,
and keeps your configuration file and your credential references on the machine you ran it from.

Classification runs in one order — what the descriptor declares, then what the content says, then
what the name suggests — and anything left over is counted as `custom/unclassified` rather than
guessed at.

If your connector maps a type onto a kind nobody registered, the probe stops and prints the
`TypeExtension` you need, ready to paste into `types.py`. That is exit `1`: a registration request,
not a failure.

A stored classification is what a sync reads later. `emit` never receives a fresh guess.

## 10. `hippo connector sync --dry-run`

```text
hippo connector sync incidents_ndjson --config ./instance.json --dry-run
```

A dry run is the real provider, read-only, publishing into a temporary workspace that is removed
on the way out. It prints the coverage a real sync would produce: pages, changes, deletions,
inventory state and per-family counts. Nothing reaches your configured memory, and no instance
needs to exist.

When you are ready to run it for real, an operator creates the instance:

```text
hippo connector enable incidents_ndjson https://incidents.example --config ./instance.json
hippo connector sync connector-abc123
```

`enable` writes the instance row, enables it, probes it and stores the classification. It needs a
signed-in installation: while a hippo has no users at all it refuses to enable a provider
connector, which is the same rule that keeps an open installation from configuring one. A
non-dry-run sync also refuses while `hippo serve` holds the database — stop the server, or use
`--dry-run`.

## 11. Packaging and the `hippo.connectors` entry point group

A connector reaches a running hippo in one of two ways.

**In-repo**, as a package under `hippo.connectors` or `hippo.connectors.examples`. The directory
name is the connector name.

**Installed**, as a distribution that declares an entry point:

```toml
[project.entry-points."hippo.connectors"]
incidents_ndjson = "incidents_ndjson:Connector"
```

An installed connector is code hippo will import and run, so it is not loaded on discovery alone.
It must be named in `HIPPO_CONNECTOR_ALLOWLIST`, and an entry point that is not listed is never
imported — it is reported, with `not allowlisted` as its reason, and skipped before its module
body could run.

Registration happens once, at startup, and only for kinds an operator has enabled. After that the
registry is frozen: a connector installed or enabled while hippo is running is picked up by the
next restart, never by the running process. That is deliberate — the vocabulary a generation was
published under must not change underneath it.

`hippo connector list` shows what this hippo can see: every built-in kind, every in-repo package,
every entry point, where each came from, whether it is enabled, how many instances it has, and the
reason for any that did not load.

## 12. The rules the kit enforces

Four rules are worth carrying in your head, because they are the ones that make a hippo memory
worth trusting.

**No model call.** A connector never asks a language model what something is. Every record it
produces comes from bytes and rules, so it can be re-derived and disputed.

**No unearned relation label.** An edge exists because something in the provider's data says so,
and it points at the span that says it. `support_required` is not advisory.

**Unknown is deny.** A policy hippo does not understand is a policy nobody passes. There is no
mode in which an unreadable ACL becomes public.

**No ingestion time.** A record carries the provider's timestamps, never hippo's. A memory whose
facts are stamped with when it happened to read them cannot answer a question about when something
was true.

The kit is how each of these stops being a rule somebody remembered.

## Where to look next

- `docs/spec/connector-developer-kit.md` — the design this guide implements.
- `tests/fakes/fixture_connector/` — the worked example quoted throughout.
- `hippo.connectors.testing` — `validate_package`, `check_capture`, `dry_run_sync` and the
  constants a fixture quotes, if you want to call the kit from your own tests rather than through
  the command line.

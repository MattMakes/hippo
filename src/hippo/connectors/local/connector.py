"""The `local` connector: one saved source directory, read as the kit's sync half.

Plan `ai_docs/plans/cdk-s5-port.md` section 4.1, decision 5, ruling R1. A local source has no
provider: its inventory is the one file `ingest.pipeline` saved, or the walk of an archive, and
there is no cursor to resume from and no deletion feed to reconcile against. So `list_changes`
answers a complete inventory in one page and `probe` reports the single partition `source:<id>`.

The connector has no `emit`. Its emission is the prose lane's `_materialize` (the readers, the
chunker and `materialize_chunk_evidence`) or the code lane's `_prepare`, both unchanged, which is
what keeps the published generation byte for byte what the pre-kit path publishes (gate CK5).

`fetch` and `fetch_policy` are implemented and pinned equal to what the lane captures and mints,
but the lane never calls them: capture stays `FileInput` inside the coordinator, because only file
capture refuses an input that changed while it was read
(`tests/unit/test_managed_pipeline_activation.py:545`). They serve probe sampling and the kit's
dry run (plan deviation 3).

S5a implements the text and prose-file branches; S5b adds the archive and code-file branches and
the `check_capture` assertion (ruling R67). The code branches answer the walk
`code_generation._capture` makes (`:314-319`), so the inventory the lane derives and the inventory
the connector reports are the same walk of the same saved bytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ...codegraph.model import CODE_MAX_FILES
from ...ingest import readers
from ...ingest.repo_capture import CaptureInventory, walk_tree
from ...knowledge.inputs import ByteInput
from .. import base, classify
from .types import EXTENSION

# One partition per source: a local source has no second scope to page over.
PARTITION_PREFIX = "source"
# The one artifact kind a saved local input becomes; `_accepted_pairs` writes the same
# (`ingest/prose_generation.py:155-162`).
FILE_KIND = "file"
# The saved bytes are never sniffed for a media type: the manifest records none, and a claimed
# content type is never consulted on this path (`ingest/readers.is_plain_prose_name`).
CONTENT_TYPE = "application/octet-stream"

# The families the two lanes derive, decided by the saved Source kind exactly as
# `managed_activation.is_code_source` decides it (`:157-160`). A `file` is decided by its name,
# through the name-level classifier (requirement R-S2-3), never by its bytes.
FAMILY_BY_KIND = {"text": "prose", "archive": "code"}


class LocalSourceConfig(BaseModel):
    """What the dispatch knows about one saved source, and nothing a provider would know.

    Ruling R65: no field name contains `credential`. A local source has none to carry.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    kind: Literal["text", "file", "archive"]
    root: str
    exclusions: tuple[str, ...] = ()
    max_files: int = CODE_MAX_FILES
    max_file_bytes: int = readers.MAX_FILE_BYTES

    @property
    def partition(self) -> str:
        return f"{PARTITION_PREFIX}:{self.source_id}"

    @property
    def path(self) -> Path:
        return Path(self.root)


DESCRIPTOR = base.ConnectorDescriptor(
    name="local",
    version="local-v1",
    families=("prose", "code"),
    # Every `KnowledgeObject` kind the two lanes write for a saved local source: the code lane's
    # repository, file and symbol objects and its data objects (`knowledge/code_binding.py:88-93`,
    # `:719-886`). The prose lane writes no knowledge object. `commit` is **not** here: a commit
    # comes from `read_history`, which `code_generation._history:397` runs only for a repository
    # tree, and a `LocalSourceConfig` is never one (ruling R72's narrowing; plan section 4.1 had
    # the superset). `resource` stays: a Mongo collection or a Cypher label in an archive binds
    # to one (`code_binding.DATA_OBJECT_KINDS`), although no fixture here holds either.
    kinds=("repository", "file", "symbol", "table", "column", "resource"),
    predicates=(),
    # `file` and `manifest` for every source, `repository` for a code tree
    # (`code_binding.py:644-702`). `history_event` is **not** here, by the same rule that drops
    # `commit`: the local lane walks no history.
    artifact_kinds=("file", "manifest", "repository"),
    # `file_lines` for every chunk span, `field` for the repository and commit-message spans.
    locator_kinds=("file_lines", "field"),
    capabilities=base.ConnectorCapabilities(
        # Ruling R1: the derivation half is the reviewed coordinator, so there is no `emit`.
        derivation="coordinator_lane",
        # `list_changes(config, None)` walks the whole partition and marks its one page complete,
        # which is what `inventory` declares. The plan predates the field and says "all false";
        # declaring it false would deny exactly the behaviour `run_coordinator_lane` requires.
        inventory=True,
    ),
    config_model=LocalSourceConfig,
    credentials=(),
    parsers=(),
    extension=EXTENSION,
)


def _is_code(config: LocalSourceConfig) -> bool:
    """The dispatch's own rule, read without importing it (ruling R54)."""
    return config.kind == "archive" or (config.kind == "file" and readers.is_code_name(config.path.name))


def _inventory(config: LocalSourceConfig) -> CaptureInventory:
    """The walk `code_generation._capture` makes for an archive or a code file (`:313-319`).

    The same call with the same rails, so the inventory this connector reports and the one the
    code lane derives from are the same walk of the same saved bytes. `walk_tree` orders by
    normalized logical path, which is the order the capture accepts them in.
    """
    return walk_tree(
        config.path,
        exclusions=config.exclusions,
        max_files=config.max_files,
        max_file_bytes=config.max_file_bytes,
    )


def coverage_warnings(inventory: CaptureInventory) -> tuple[str, ...]:
    """One page warning per exclusion reason, with the number of entries that carried it.

    Spelled `excluded.<reason>:<count>`, which `ConnectorDescriptor`'s `Code` alphabet admits.
    `connectors/git/connector.py` carries the same eight lines: a connector package is
    self-contained, so neither imports the other.
    """
    counts: dict[str, int] = {}
    for item in inventory.exclusions:
        counts[item.reason] = counts.get(item.reason, 0) + 1
    return tuple(f"excluded.{reason}:{count}" for reason, count in sorted(counts.items()))


def _decision(config: LocalSourceConfig) -> classify.ItemDecision:
    """The name-level classification of the saved input (requirement R-S2-3).

    The item carries no bytes, so the content rules cannot fire and the decision is the
    declaration for a kind the Source row already settles, or `readers.is_code_name` /
    `readers.is_plain_prose_name` for a file the row settles by name.
    """
    declared = FAMILY_BY_KIND.get(config.kind)
    declarations = (base.PathDeclaration(pattern="*", family=declared),) if declared is not None else ()
    item = classify.SampledItem(partition=config.partition, path=config.path.name, data=b"")
    return classify.classify_item(item, classify.classifier_spec(declarations=declarations))


class LocalConnector:
    """The sync half of the local source families; the lane owns the derivation half."""

    descriptor = DESCRIPTOR

    def probe(self, config: LocalSourceConfig, clock: base.Clock) -> base.Classification:
        """One partition, `source:<id>`, whose family is the one the dispatch would choose.

        `clock` exists for a connector's own bounded HTTP and is unused here: a local source is
        read from disk, and no observed instant enters the classification.
        """
        registry = base.current_registry()
        decision = _decision(config)
        family = decision.family if decision.family in ("prose", "code") else "prose"
        partition = base.PartitionClassification(
            partition=config.partition,
            family=family,
            mapping=base.TypeMapping(family=family, classifier=classify.classifier_spec()),
            capabilities=self.descriptor.capabilities,
            sample_count=1,
            counts={family: 1},
            warnings=decision.warnings,
            evidence=(decision.evidence,),
        )
        return base.Classification(
            connector=self.descriptor.name,
            connector_version=self.descriptor.version,
            registry_fingerprint=registry.fingerprint(),
            partitions=(partition,),
        )

    def list_changes(self, config: LocalSourceConfig, cursor: base.SyncCursor | None) -> base.ChangePage:
        """The complete inventory of one saved source. There is no cursor to resume from.

        A pasted text or a prose file is the one saved name. An archive or a code file is the
        walk of the saved bytes: one upsert per capturable entry, in walk order, with one
        coverage warning per exclusion reason. A local source has no provider revision.
        """
        if _is_code(config):
            inventory = _inventory(config)
            return base.ChangePage(
                partition=config.partition,
                changes=tuple(
                    base.Change(ref=self._ref(config, item.logical_path), operation="upsert")
                    for item in inventory.inputs
                ),
                next_cursor=None,
                complete=True,
                warnings=coverage_warnings(inventory),
            )
        return base.ChangePage(
            partition=config.partition,
            changes=(base.Change(ref=self._ref(config, config.path.name), operation="upsert"),),
            next_cursor=None,
            complete=True,
        )

    def fetch(self, config: LocalSourceConfig, ref: base.ExternalRef) -> base.RawFetch:
        """The saved bytes, under the canonical URI `_accepted_pairs` writes (`:160`)."""
        return base.RawFetch(
            ref=ref,
            data=self._member(config, ref),
            content_type=CONTENT_TYPE,
            external_id=ref.external_id,
            canonical_uri=f"{config.partition}/{ref.external_id}",
        )

    def fetch_policy(self, config: LocalSourceConfig, ref: base.ExternalRef) -> base.PolicyObservation:
        """The workspace grant the lanes mint (`prose_generation.py:143-149`).

        `PolicyObservation` has no origin (review m9), so `local_curated` is not restated here;
        the mode is what the two records have in common, and a local source names no principal.
        """
        return base.PolicyObservation(ref=ref, state="known", mode="workspace")

    def _ref(self, config: LocalSourceConfig, external_id: str) -> base.ExternalRef:
        return base.ExternalRef(partition=config.partition, artifact_kind=FILE_KIND, external_id=external_id)

    def _member(self, config: LocalSourceConfig, ref: base.ExternalRef) -> bytes:
        """The bytes of one walked entry, or of the one saved input.

        Re-walking is also the traversal guard: a reference is answered only when the walk
        itself produced that logical path, so a `..` or an absolute name reaches nothing. An
        archive member's bytes are already in hand from the walk; a file's are read from disk.
        """
        if ref.partition != config.partition:
            raise base.ContractError("An external reference belongs to its own source partition")
        if _is_code(config):
            for item in _inventory(config).inputs:
                if item.logical_path == ref.external_id:
                    return item.data if type(item) is ByteInput else item.path.read_bytes()
            raise base.ContractError("This source captured no member under that name")
        if ref.external_id != config.path.name:
            raise base.ContractError("A local source holds exactly one saved input")
        return config.path.read_bytes()

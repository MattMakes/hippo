"""The `git` connector: one public repository, read as the kit's sync half.

Plan `ai_docs/plans/cdk-s5-port.md` section 4.2, decision 6, ruling R1. A repository has no
provider API here: its inventory is the walk of a checkout this build owns, so `list_changes`
clones once, reads the head and answers a complete inventory in one page, and there is no cursor
to resume from and no deletion feed to reconcile against.

The connector has no `emit`. Its emission is the code lane's `_prepare` - `extract_code`,
`read_history`, `prepare_code_chunks`, `materialize_code_evidence` and `bind_history` - and
`staged_code`, all unchanged, which is what keeps the published generation byte for byte what the
pre-kit path publishes (gate CK5). **History is read by the coordinator, never inside a connector
method**, because `read_history` is a `git` subprocess that needs the extracted symbols
(`code_generation._history`).

The checkout lifecycle stays in `managed_activation._run_code_build`: discard before, discard in
`finally`. This module never removes one.

`fetch` and `fetch_policy` are implemented and pinned equal to what the lane captures and mints,
but the lane never calls them: capture stays the coordinator's own tree walk (plan deviation 3).
They serve probe sampling and the kit's dry run.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ...codegraph.model import CODE_MAX_FILES
from ...ingest import readers, repos
from ...ingest.repo_capture import CaptureInventory, repository_descriptor, walk_tree
from .. import base, classify
from .types import EXTENSION

# One partition per source, as for `local`: a managed repository source is one clone URL.
PARTITION_PREFIX = "source"
FILE_KIND = "file"
CONTENT_TYPE = "application/octet-stream"
# The one family this connector answers for: a repository is code, whatever prose it also holds.
FAMILY = "code"
# What a checkout carries when it is one: the history capability is observed, not assumed.
GIT_DIRECTORY = ".git"


class GitSourceConfig(BaseModel):
    """What the dispatch knows about one managed repository build.

    Ruling R65: no field name contains `credential`. A credential never reaches this model at
    all - `repository_descriptor` refuses a URL carrying userinfo before anything is cloned.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    url: str
    checkout: str
    depth: int
    git_timeout_seconds: float
    exclusions: tuple[str, ...] = ()
    max_files: int = CODE_MAX_FILES
    max_file_bytes: int = readers.MAX_FILE_BYTES

    @property
    def partition(self) -> str:
        return f"{PARTITION_PREFIX}:{self.source_id}"

    @property
    def path(self) -> Path:
        return Path(self.checkout)


DESCRIPTOR = base.ConnectorDescriptor(
    name="git",
    version="git-v1",
    families=(FAMILY,),
    # Every `KnowledgeObject` kind a repository build writes: the code lane's repository, file,
    # symbol and commit objects and its data objects (`knowledge/code_binding.py:719-886`,
    # `code_history.py:943`).
    kinds=("repository", "file", "symbol", "commit", "table", "column", "resource"),
    predicates=(),
    # `file` and `manifest` for the capture, `repository` and `history_event` for the walked
    # history (`code_binding.py:644-702`, `code_history.py:6`).
    artifact_kinds=("file", "manifest", "repository", "history_event"),
    # `file_lines` for every chunk span, `field` for the repository and commit-message spans.
    locator_kinds=("file_lines", "field"),
    capabilities=base.ConnectorCapabilities(
        # Ruling R1: the derivation half is the reviewed code coordinator, so there is no `emit`.
        derivation="coordinator_lane",
        # A repository carries commit history, which is the one capability this connector has
        # that `local` does not. The coordinator reads it; the declaration is what says it exists.
        history=True,
        # `list_changes(config, None)` walks the whole checkout and marks its one page complete.
        inventory=True,
    ),
    config_model=GitSourceConfig,
    credentials=(),
    parsers=(),
    extension=EXTENSION,
)


def _inventory(config: GitSourceConfig) -> CaptureInventory:
    """The walk `code_generation._capture` makes for a checkout (`:313-319`), with the same rails."""
    return walk_tree(
        config.path,
        exclusions=config.exclusions,
        max_files=config.max_files,
        max_file_bytes=config.max_file_bytes,
    )


def coverage_warnings(inventory: CaptureInventory) -> tuple[str, ...]:
    """One page warning per exclusion reason, with the number of entries that carried it.

    Spelled `excluded.<reason>:<count>`. `connectors/local/connector.py` carries the same eight
    lines: a connector package is self-contained, so neither imports the other.
    """
    counts: dict[str, int] = {}
    for item in inventory.exclusions:
        counts[item.reason] = counts.get(item.reason, 0) + 1
    return tuple(f"excluded.{reason}:{count}" for reason, count in sorted(counts.items()))


class GitConnector:
    """The sync half of a managed repository source; the code lane owns the derivation half."""

    descriptor = DESCRIPTOR

    def probe(self, config: GitSourceConfig, clock: base.Clock) -> base.Classification:
        """One partition, `source:<id>`, of the code family, with history as the checkout shows it.

        Pure in the clock and cheap on purpose: it reads whether the checkout is a clone, never
        the tree, so it clones nothing, walks nothing, and two probes an instant apart classify
        identically (the kit's `probe_deterministic`, review M13).
        """
        cloned = (config.path / GIT_DIRECTORY).exists()
        capabilities = self.descriptor.capabilities.replace(history=cloned)
        evidence = base.ClassificationEvidence(
            level="family",
            rule="descriptor",
            detector="git_checkout",
            subject=config.partition,
            outcome=FAMILY,
        )
        partition = base.PartitionClassification(
            partition=config.partition,
            family=FAMILY,
            mapping=base.TypeMapping(family=FAMILY, classifier=classify.classifier_spec()),
            capabilities=capabilities,
            sample_count=1,
            counts={FAMILY: 1},
            warnings=() if cloned else ("checkout_absent",),
            evidence=(evidence,),
        )
        return base.Classification(
            connector=self.descriptor.name,
            connector_version=self.descriptor.version,
            registry_fingerprint=base.current_registry().fingerprint(),
            partitions=(partition,),
        )

    def list_changes(self, config: GitSourceConfig, cursor: base.SyncCursor | None) -> base.ChangePage:
        """Refuse, clone, read the head, walk. The four steps of plan section 4.2, in order.

        `repository_descriptor` runs first, so a URL carrying a personal access token refuses
        before any clone exists - the refusal `add_repo` and `_run_code_build` already make.
        `repos.clone_repo` is reached through the module attribute, so the managed-clone
        monkeypatch of `tests/unit/test_managed_code_activation.py:129-140` still applies, and a
        checkout this operation already holds is not re-cloned.
        """
        repository_descriptor(config.url)
        checkout = config.path
        if not checkout.exists():
            repos.clone_repo(config.url, checkout, depth=config.depth)
        head = repos.head_revision(checkout, timeout=config.git_timeout_seconds)
        inventory = _inventory(config)
        return base.ChangePage(
            partition=config.partition,
            changes=tuple(
                base.Change(ref=self._ref(config, item.logical_path, head), operation="upsert")
                for item in inventory.inputs
            ),
            next_cursor=None,
            complete=True,
            warnings=coverage_warnings(inventory),
        )

    def fetch(self, config: GitSourceConfig, ref: base.ExternalRef) -> base.RawFetch:
        """One walked file's bytes, read from the checkout, under the lane's canonical URI form."""
        return base.RawFetch(
            ref=ref,
            data=self._member(config, ref).read_bytes(),
            content_type=CONTENT_TYPE,
            external_id=ref.external_id,
            canonical_uri=f"{config.partition}/{ref.external_id}",
            provider_revision=ref.provider_revision,
        )

    def fetch_policy(self, config: GitSourceConfig, ref: base.ExternalRef) -> base.PolicyObservation:
        """The workspace grant the code lane mints (`code_generation.py:590-596`).

        `PolicyObservation` has no origin (review m9), so `local_curated` is not restated here;
        a public repository names no provider principal.
        """
        return base.PolicyObservation(ref=ref, state="known", mode="workspace")

    def _ref(self, config: GitSourceConfig, external_id: str, head: str) -> base.ExternalRef:
        return base.ExternalRef(
            partition=config.partition,
            artifact_kind=FILE_KIND,
            external_id=external_id,
            provider_revision=head,
        )

    def _member(self, config: GitSourceConfig, ref: base.ExternalRef) -> Path:
        """One walked entry's path. Re-walking is the traversal guard: a name the walk never
        produced reaches nothing, so `..` and an absolute path are refused rather than opened.
        """
        if ref.partition != config.partition:
            raise base.ContractError("An external reference belongs to its own source partition")
        for item in _inventory(config).inputs:
            if item.logical_path == ref.external_id:
                return item.path
        raise base.ContractError("This checkout holds no capturable file under that name")

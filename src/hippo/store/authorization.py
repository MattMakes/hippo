"""Durable authorization invalidation, committed with the mutation it describes."""

from functools import wraps

EPOCH_KEY = "authorization_epoch"


def authorization_epoch(store) -> int:
    store._ensure_knowledge_ready()
    value = store.get_meta(EPOCH_KEY)
    if value is None:
        return 0
    if type(value) is not int or value < 0:
        raise RuntimeError("Invalid authorization epoch; refuse cached evidence")
    return value


def bump_authorization_epoch(store) -> int:
    with store.transaction():
        if store.knowledge_backend == "neo4j":
            row = store.run_one(
                "MATCH (s:Settings {id:'global'}) "
                "SET s.authorization_epoch=coalesce(s.authorization_epoch,0)+1 "
                "RETURN s.authorization_epoch AS value"
            )
            if row is None or type(row["value"]) is not int or row["value"] < 1:
                raise RuntimeError("Invalid authorization epoch; mutation rolled back")
            return row["value"]
        value = authorization_epoch(store) + 1
        store.set_meta(EPOCH_KEY, value)
        return value


def lock_authorization(store) -> None:
    """Caller owns a transaction; serialize decisions before reading user/connector state."""
    if store.knowledge_backend == "neo4j":
        store.run(
            "MATCH (s:Settings {id:'global'}) "
            "SET s._authorization_lock=true REMOVE s._authorization_lock RETURN s.id AS id"
        )
    authorization_epoch(store)  # Corrupt state cannot become an earlier valid counter.


def configured_provider(connector) -> bool:
    return connector.kind != "local" and (
        connector.enabled or connector.credential_ref is not None or connector.config_json != "{}"
    )


def safer_connector(existing, candidate) -> bool:
    """Permit deactivation/credential removal without permitting new access in open mode."""
    if existing is None:
        return False
    return (
        not (candidate.enabled and not existing.enabled)
        and candidate.credential_ref in (None, existing.credential_ref)
        and candidate.config_json in ("{}", existing.config_json)
        and candidate.capabilities_json in ("{}", existing.capabilities_json)
    )


def permission_mutation(function):
    """Legacy permission writers participate in the same atomic revocation barrier."""

    @wraps(function)
    def wrapped(store, *args, **kwargs):
        with store.transaction():
            lock_authorization(store)
            had_users = store.count_users() > 0
            result = function(store, *args, **kwargs)
            if had_users or function.__name__ == "create_user":
                # Persist across last-user removal, including upgraded stores
                # whose existing users predate this marker. Failed writes roll
                # the marker back together with the permission mutation.
                store.set_meta("has_had_users", True)
            if function.__name__ == "delete_user" and store.count_users() == 0:
                if any(configured_provider(record) for record in store._knowledge_rows("Connector")):
                    raise ValueError("Clear provider connector configuration before removing the last user")
            bump_authorization_epoch(store)
            return result

    return wrapped


def metadata_mutation(function):
    """Reviewed identity-mapping configuration is itself an authorization grant."""

    @wraps(function)
    def wrapped(store, key, value):
        if key != "reviewed_mapping_authorities":
            return function(store, key, value)
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise ValueError("Reviewed mapping authorities require a list of nonempty names")
        with store.transaction():
            lock_authorization(store)
            result = function(store, key, value)
            bump_authorization_epoch(store)
            return result

    return wrapped


# Every registered record is classified explicitly; unknown additions fail closed.
RECORD_EPOCHS = {
    **dict.fromkeys(("WorkspaceMembership", "GroupMembership", "AccessPolicy", "Connector"), "authorization"),
    **dict.fromkeys(
        (
            "Artifact",
            "ArtifactRevision",
            "EvidenceSpan",
            "KnowledgeObject",
            "ObjectObservation",
            "Assertion",
            "AssertionVersion",
            "AssertionSupport",
            "NativeBinding",
            "Generation",
            "GenerationMember",
            "GenerationEvidenceMember",
            "IndexManifest",
            "LinkGeneration",
            "HistoryManifest",
            "DerivedRecord",
            "DerivedDependency",
            "RetrievalView",
            "Section",
            "SectionMember",
            "ConflictSet",
            "Alias",
        ),
        "content",
    ),
    **dict.fromkeys(
        (
            "Workspace",
            "SyncState",
            "SyncRun",
            "MaintenanceJob",
            "SourceEvent",
            "PurgeJob",
            "IndexEvent",
            "ConsumerAck",
            "QuerySnapshot",
            "SnapshotReference",
        ),
        "bookkeeping",
    ),
    "Suppression": "suppression",
}


def epoch(store, key):
    store._ensure_knowledge_ready()
    value = store.get_meta(key)
    if value is None:
        return 0
    if type(value) is not int or value < 0:
        raise RuntimeError(f"Invalid {key}; refuse stale state")
    return value


def bump_epoch(store, key):
    # All callers own the shared authorization transaction lock, including Neo4j.
    value = epoch(store, key) + 1
    store.set_meta(key, value)
    return value


def record_mutation(store, record, existing=None):
    name = type(record).__name__
    classification = RECORD_EPOCHS[name]
    if name in ("Artifact", "Generation"):
        store.begin_managed_source(record.source_id)
    if classification in ("authorization", "suppression") or (
        name == "Artifact"
        and existing is not None
        and (record.policy_id != existing.policy_id or record.deleted_at != existing.deleted_at)
    ):
        store._bump_authorization_epoch()
    if classification in ("content", "suppression"):
        bump_epoch(store, "content_epoch")
    if classification == "suppression":
        bump_epoch(store, "suppression_epoch")

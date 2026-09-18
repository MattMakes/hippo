# Controlled generation embedding profile binding

Status: implemented and independently reviewed; all four gates pass. No production selection or writer activation.

## Contract

Implement `knowledge/generation_profiles.py` with local-only `embedding_mode(generation)` and `validate_generation_profile(store, generation, manifest_revision_id=None)`. The validator returns a frozen `GenerationProfile(profile: StoredEmbeddingProfile, config_fingerprint: str)` and never returns the accepted inventory. An explicit revision is the staging bind input; omitted revision requires a controlled verified binding. Neither API authorizes evidence or attests remote execution.

The canonical accepted v1 manifest has exactly the current AcceptedInputs keys and is mirrored as `ArtifactRevision.metadata_json.accepted_manifest_v1`. Reconstruct the existing immutable AcceptedInputs values to validate types, input keys, ordered dispositions, limits, raw references, and canonical manifest hash without raw I/O. Configuration embeds the closed safe descriptor at `embedding_profile`; its fingerprint equals Generation.embedding_profile. Configuration fingerprint is SHA-256 of canonical configuration JSON.

The local manifest Artifact uses kind `manifest`, source/workspace, stable external_id `accepted-inputs-v1`, no connector/provider instance, and recommended canonical URI `source:{source_id}/accepted-inputs-v1`. Its revision has provider_revision None, immutable content-addressed raw URI and canonical content hash. Artifact canonical_uri, policy_id and deleted_at are mutable presentation/access state and cannot invalidate a sealed profile binding. Current authorization remains an independent prerequisite.

The exact GenerationMember inventory is the accepted local-file revisions plus one manifest revision. Every original matches its accepted normalized path, source/workspace-derived Artifact ID, raw input key, hash, provider revision and immutable raw URI. Reject duplicate/extra/missing revisions or artifacts and container mappings. Recompute generation_for_inputs over all original pairs plus the manifest pair and the accepted configuration; require the same generation ID/hash. Accepted manifest inputs never include the manifest itself or generated output IDs. Changing configuration creates a new manifest revision and generation; unchanged original revisions are reused without changing immutable metadata/observed_at.

Add `GenerationQueries.bind_generation_embedding_profile(generation_id, manifest_revision_id, *, job_id, lease_owner, fencing_token, fault_hook=None)`. Under the existing checked build fence require staging, no sealed IndexManifest, and a valid exact binding. Write only `embedding_mode=verified_v1` and `embedding_manifest_revision_id`, preserving other coverage fields. First bind advances content_epoch only; exact idempotent retry requires a live fence and changes no epoch. Conflicting binding is rejected. No HTTP/filesystem operations or heartbeat workers belong inside this transaction.

Absent/explicit `legacy_tag_v1` mode preserves established compatibility, including digest-shaped tags. Unknown modes/dangling pointers fail closed. Generic Generation admission cannot introduce verified mode or pointer, and existing lifecycle guards prohibit generic changes/removal. New controlled binding proves stored identity consistency only: preparation must separately resolve/validate the actual model outside locks. Staging mode grants no read or publication eligibility.

Verified seals append a versioned synthetic evidence checksum row committing marker/revision/profile/config fingerprint; existing unmarked/legacy checksum bytes remain unchanged. Seal/publication revalidate the exact binding, IndexManifest.config_fingerprint, and the descriptor dimension across every present managed passage, native embedding and selected ProseExtraction vector. Empty inventories remain valid. No schema/model descriptor changes or migrations.

## Ownership and validation

Owned: new generation_profiles.py, narrow store/generations.py hooks, new test_generation_profiles.py, this plan and dedicated ledger. Context/routing/projection/writer files are owned by other agents. Use TDD, Fake and disposable Ladybug. Root reserves Neo4j and owns independent review, gates and publication.

Tests cover valid bind/seal/reopen, exact closure, stale fences, unknown modes/generic preseed, descriptor/config/dimension mismatch, rollback/idempotence, immutable original reuse, mutable Artifact metadata compatibility, old checksum preservation, empty input and no remote/raw I/O under the binding transaction. Reader helpers expose only safe profile identity and require prior evidence authorization; hidden accepted inventory is never added to audience fingerprints or DTOs.

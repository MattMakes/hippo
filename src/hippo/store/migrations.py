"""Versioned additive evidence schema; reject incompatible stores before mutation.

Ladybug schema/data changes share a transaction. Neo4j journals idempotent schema
steps separately, then atomically commits data transforms and the completion row.
An incomplete Neo4j migration is never declared ready and must resume before use.
"""

from __future__ import annotations

import json
import types
from datetime import datetime
from typing import Annotated, Literal, Union, get_args, get_origin

from ..knowledge.identity import canonical_json, text_hash
from ..knowledge.model import RECORD_TYPES, Workspace

CURRENT_SCHEMA_VERSION = 5
# Published by 4246f5e: never derive v2 from the evolving models.
V2_DESCRIPTOR = json.loads(
    """[2, {
"AccessPolicy": {"allow_groups":"STRING[]","allow_users":"STRING[]","deny_groups":"STRING[]","deny_users":"STRING[]","expires_at":"TIMESTAMP","id":"STRING","identity_key":"STRING","mode":"STRING","verified_at":"TIMESTAMP","workspace_id":"STRING"},
"Alias": {"alias_key":"STRING","authority":"STRING","id":"STRING","identity_key":"STRING","namespace":"STRING","status":"STRING","support_span_ids":"STRING[]","target_object_id":"STRING","workspace_id":"STRING"},
"Artifact": {"canonical_uri":"STRING","connector_id":"STRING","deleted_at":"TIMESTAMP","external_id":"STRING","id":"STRING","identity_key":"STRING","kind":"STRING","policy_id":"STRING","provider_instance":"STRING","source_id":"STRING","workspace_id":"STRING"},
"ArtifactRevision": {"artifact_id":"STRING","content_hash":"STRING","id":"STRING","identity_key":"STRING","lifecycle":"STRING","metadata_json":"STRING","observed_at":"TIMESTAMP","provider_revision":"STRING","raw_uri":"STRING","source_precision":"STRING","source_timestamp_original":"STRING","source_timezone":"STRING","source_updated_at":"TIMESTAMP"},
"Assertion": {"id":"STRING","identity_key":"STRING","object_id":"STRING","predicate":"STRING","scope_key":"STRING","subject_id":"STRING","workspace_id":"STRING"},
"AssertionSupport": {"assertion_version_id":"STRING","derivation_group":"STRING","id":"STRING","identity_key":"STRING","span_id":"STRING"},
"AssertionVersion": {"assertion_id":"STRING","confidence":"DOUBLE","evidence_class":"STRING","id":"STRING","identity_key":"STRING","recorded_from":"TIMESTAMP","recorded_to":"TIMESTAMP","rule_version":"STRING","source_timestamp_original":"STRING","source_timezone":"STRING","status":"STRING","temporal_basis":"STRING","temporal_precision":"STRING","valid_from":"TIMESTAMP","valid_to":"TIMESTAMP","validity_kind":"STRING"},
"ConflictSet": {"assertion_version_ids":"STRING[]","id":"STRING","identity_key":"STRING","resolution_rule":"STRING","resolution_status":"STRING","scope_key":"STRING","support_span_ids":"STRING[]","valid_from":"TIMESTAMP","valid_to":"TIMESTAMP","workspace_id":"STRING"},
"Connector": {"capabilities_json":"STRING","config_json":"STRING","credential_ref":"STRING","enabled":"BOOLEAN","id":"STRING","identity_key":"STRING","instance_url":"STRING","kind":"STRING","workspace_id":"STRING"},
"ConsumerAck": {"acknowledged_at":"TIMESTAMP","attempt_count":"INT64","consumer_id":"STRING","event_id":"STRING","fencing_token":"INT64","id":"STRING","identity_key":"STRING","lease_expires_at":"TIMESTAMP","lease_owner":"STRING","retry_at":"TIMESTAMP","state":"STRING"},
"DerivedDependency": {"derived_record_id":"STRING","id":"STRING","identity_key":"STRING","input_id":"STRING","input_kind":"STRING","input_version":"STRING"},
"DerivedRecord": {"dependency_fingerprint":"STRING","id":"STRING","identity_key":"STRING","input_binding_ids":"STRING[]","input_revision_ids":"STRING[]","model_version":"STRING","rule_version":"STRING","state":"STRING","view_kind":"STRING","workspace_id":"STRING"},
"EvidenceSpan": {"id":"STRING","identity_key":"STRING","locator_json":"STRING","locator_kind":"STRING","policy_id":"STRING","revision_id":"STRING","text":"STRING","text_hash":"STRING"},
"Generation": {"coverage_json":"STRING","created_at":"TIMESTAMP","embedding_profile":"STRING","id":"STRING","identity_key":"STRING","linker_version":"STRING","manifest_hash":"STRING","parent_id":"STRING","parser_version":"STRING","published_at":"TIMESTAMP","source_id":"STRING","status":"STRING"},
"GenerationMember": {"artifact_revision_id":"STRING","generation_id":"STRING","id":"STRING","identity_key":"STRING"},
"GroupMembership": {"enabled":"BOOLEAN","group_id":"STRING","id":"STRING","identity_key":"STRING","mapping_authority":"STRING","policy_epoch":"INT64","principal_id":"STRING","workspace_id":"STRING"},
"HistoryManifest": {"assertion_version_ids":"STRING[]","coverage_json":"STRING","id":"STRING","identity_key":"STRING","knowledge_cutoff":"TIMESTAMP","link_generation_ids":"STRING[]","retention_gaps":"STRING[]","revision_ids":"STRING[]","temporal_selector_json":"STRING","workspace_id":"STRING"},
"IndexEvent": {"aggregate_id":"STRING","created_at":"TIMESTAMP","dedupe_key":"STRING","generation_id":"STRING","id":"STRING","identity_key":"STRING","kind":"STRING","payload_json":"STRING","sequence":"INT64","state":"STRING","workspace_id":"STRING"},
"IndexManifest": {"checksums":"STRING","config_fingerprint":"STRING","generation_id":"STRING","id":"STRING","identity_key":"STRING","missing_optional":"STRING[]","profile_fingerprint":"STRING","ready":"BOOLEAN","required_representations":"STRING[]"},
"KnowledgeObject": {"canonical_key":"STRING","id":"STRING","identity_key":"STRING","kind":"STRING","workspace_id":"STRING"},
"LinkGeneration": {"assertion_version_ids":"STRING[]","coverage_json":"STRING","created_at":"TIMESTAMP","id":"STRING","identity_key":"STRING","input_manifest_hash":"STRING","linker_version":"STRING","workspace_id":"STRING"},
"MaintenanceJob": {"attempt_count":"INT64","cursor_json":"STRING","error_code":"STRING","expected_parent_id":"STRING","fencing_token":"INT64","id":"STRING","identity_key":"STRING","input_fingerprint":"STRING","job_key":"STRING","kind":"STRING","lease_expires_at":"TIMESTAMP","lease_owner":"STRING","phase":"STRING","retry_at":"TIMESTAMP","scope_key":"STRING","source_id":"STRING","status":"STRING"},
"NativeBinding": {"generation_id":"STRING","id":"STRING","identity_key":"STRING","native_id":"STRING","native_kind":"STRING","object_id":"STRING","span_id":"STRING"},
"ObjectObservation": {"attributes_json":"STRING","evidence_class":"STRING","id":"STRING","identity_key":"STRING","object_id":"STRING","recorded_from":"TIMESTAMP","recorded_to":"TIMESTAMP","revision_id":"STRING","source_timestamp_original":"STRING","source_timezone":"STRING","span_id":"STRING","temporal_basis":"STRING","temporal_precision":"STRING","valid_from":"TIMESTAMP","valid_to":"TIMESTAMP","validity_kind":"STRING"},
"PurgeJob": {"audit_code":"STRING","backup_disposition":"STRING","completed_at":"TIMESTAMP","created_at":"TIMESTAMP","derived_status":"STRING","id":"STRING","identity_key":"STRING","phase":"STRING","raw_status":"STRING","removal_manifest_ids":"STRING[]","request_key":"STRING","saved_output_status":"STRING","scope_key":"STRING","workspace_id":"STRING"},
"QuerySnapshot": {"created_at":"TIMESTAMP","history_manifest_ids":"STRING[]","id":"STRING","identity_key":"STRING","knowledge_cutoff":"TIMESTAMP","link_generation_id":"STRING","policy_fingerprint":"STRING","profile_fingerprint":"STRING","settings_fingerprint":"STRING","sources":"STRING","suppression_epoch":"INT64","temporal":"STRING","workspace_id":"STRING"},
"RetrievalView": {"dependency_fingerprint":"STRING","derivation_version":"STRING","derived_record_id":"STRING","id":"STRING","identity_key":"STRING","object_id":"STRING","source_revision_id":"STRING","span_id":"STRING","text":"STRING","text_profile":"STRING","vector_profile":"STRING","view_kind":"STRING"},
"Section": {"breadcrumb":"STRING[]","id":"STRING","identity_key":"STRING","ordinal":"INT64","original_heading":"STRING","original_span_ids":"STRING[]","parent_section_id":"STRING","source_revision_id":"STRING"},
"SectionMember": {"child_id":"STRING","child_kind":"STRING","id":"STRING","identity_key":"STRING","ordinal":"INT64","section_id":"STRING"},
"SourceEvent": {"acceptance_state":"STRING","artifact_id":"STRING","connector_id":"STRING","dedupe_key":"STRING","delivery_id":"STRING","id":"STRING","identity_key":"STRING","operation":"STRING","payload_hash":"STRING","provider_artifact_id":"STRING","provider_instance":"STRING","provider_revision":"STRING","provider_sequence":"STRING","received_at":"TIMESTAMP"},
"Suppression": {"all_principals":"BOOLEAN","created_at":"TIMESTAMP","epoch":"INT64","id":"STRING","identity_key":"STRING","principal_ids":"STRING[]","reason":"STRING","restoration_barrier":"STRING","scope_key":"STRING","target_id":"STRING","target_kind":"STRING","view_applicability":"STRING","workspace_id":"STRING"},
"SyncRun": {"attempt_count":"INT64","connector_id":"STRING","cursor_json":"STRING","error_code":"STRING","expected_parent_id":"STRING","fencing_token":"INT64","id":"STRING","identity_key":"STRING","input_fingerprint":"STRING","lease_expires_at":"TIMESTAMP","lease_owner":"STRING","phase":"STRING","retry_at":"TIMESTAMP","run_key":"STRING","scope_key":"STRING","source_id":"STRING","status":"STRING"},
"SyncState": {"connector_id":"STRING","cursor_json":"STRING","error_code":"STRING","id":"STRING","identity_key":"STRING","last_reconciled_at":"TIMESTAMP","last_success_at":"TIMESTAMP","partition_key":"STRING","watermark":"STRING"},
"Workspace": {"id":"STRING","identity_key":"STRING","name":"STRING"},
"WorkspaceMembership": {"enabled":"BOOLEAN","id":"STRING","identity_key":"STRING","mapping_authority":"STRING","policy_epoch":"INT64","principal_id":"STRING","workspace_id":"STRING"}
},[["SUBJECT_OBJECT","Assertion","KnowledgeObject"],["TARGET_OBJECT","Assertion","KnowledgeObject"],["VERSION_OF","AssertionVersion","Assertion"],["SUPPORT_VERSION","AssertionSupport","AssertionVersion"],["SUPPORT_SPAN","AssertionSupport","EvidenceSpan"],["REVISION_OF","ArtifactRevision","Artifact"],["SPAN_REVISION","EvidenceSpan","ArtifactRevision"],["OBSERVED_OBJECT","ObjectObservation","KnowledgeObject"],["OBSERVATION_SPAN","ObjectObservation","EvidenceSpan"],["MEMBER_GENERATION","GenerationMember","Generation"],["MEMBER_REVISION","GenerationMember","ArtifactRevision"],["BINDING_OBJECT","NativeBinding","KnowledgeObject"],["BINDING_SPAN","NativeBinding","EvidenceSpan"],["SECTION_PARENT","SectionMember","Section"]],{"active_generation_id":"STRING","generation_lock":"INT64","generation_version":"INT64","workspace_id":"STRING"},{"artifact_revision_id":"STRING","content_kind":"STRING","embedding_profile":"STRING","generation_id":"STRING","parent_passage_id":"STRING","span_id":"STRING"}]"""
)
V2_CHECKSUM = "f4419a33c505b28fc7239c6aa6ac323c9bbcb926159df457c2a3876f0bbc5b0f"

V3_DESCRIPTOR = json.loads(
    '[3,{"AccessPolicy":{"allow_groups":"STRING[]","allow_users":"STRING[]","deny_groups":"STRING[]","deny_users":"STRING[]","expires_at":"TIMESTAMP","id":"STRING","identity_key":"STRING","mode":"STRING","origin":"STRING","scope_key":"STRING","verified_at":"TIMESTAMP","workspace_id":"STRING"},"Alias":{"alias_key":"STRING","authority":"STRING","id":"STRING","identity_key":"STRING","namespace":"STRING","status":"STRING","support_span_ids":"STRING[]","target_object_id":"STRING","workspace_id":"STRING"},"Artifact":{"canonical_uri":"STRING","connector_id":"STRING","deleted_at":"TIMESTAMP","external_id":"STRING","id":"STRING","identity_key":"STRING","kind":"STRING","policy_id":"STRING","provider_instance":"STRING","source_id":"STRING","workspace_id":"STRING"},"ArtifactRevision":{"artifact_id":"STRING","content_hash":"STRING","id":"STRING","identity_key":"STRING","lifecycle":"STRING","metadata_json":"STRING","observed_at":"TIMESTAMP","provider_revision":"STRING","raw_uri":"STRING","source_precision":"STRING","source_timestamp_original":"STRING","source_timezone":"STRING","source_updated_at":"TIMESTAMP"},"Assertion":{"id":"STRING","identity_key":"STRING","object_id":"STRING","predicate":"STRING","scope_key":"STRING","subject_id":"STRING","workspace_id":"STRING"},"AssertionSupport":{"assertion_version_id":"STRING","derivation_group":"STRING","id":"STRING","identity_key":"STRING","span_id":"STRING"},"AssertionVersion":{"assertion_id":"STRING","confidence":"DOUBLE","evidence_class":"STRING","id":"STRING","identity_key":"STRING","recorded_from":"TIMESTAMP","recorded_to":"TIMESTAMP","rule_version":"STRING","source_timestamp_original":"STRING","source_timezone":"STRING","status":"STRING","temporal_basis":"STRING","temporal_precision":"STRING","valid_from":"TIMESTAMP","valid_to":"TIMESTAMP","validity_kind":"STRING"},"ConflictSet":{"assertion_version_ids":"STRING[]","id":"STRING","identity_key":"STRING","resolution_rule":"STRING","resolution_status":"STRING","scope_key":"STRING","support_span_ids":"STRING[]","valid_from":"TIMESTAMP","valid_to":"TIMESTAMP","workspace_id":"STRING"},"Connector":{"capabilities_json":"STRING","config_json":"STRING","credential_ref":"STRING","enabled":"BOOLEAN","id":"STRING","identity_key":"STRING","instance_url":"STRING","kind":"STRING","workspace_id":"STRING"},"ConsumerAck":{"acknowledged_at":"TIMESTAMP","attempt_count":"INT64","consumer_id":"STRING","event_id":"STRING","fencing_token":"INT64","id":"STRING","identity_key":"STRING","lease_expires_at":"TIMESTAMP","lease_owner":"STRING","retry_at":"TIMESTAMP","state":"STRING"},"DerivedDependency":{"derived_record_id":"STRING","id":"STRING","identity_key":"STRING","input_id":"STRING","input_kind":"STRING","input_version":"STRING"},"DerivedRecord":{"dependency_fingerprint":"STRING","id":"STRING","identity_key":"STRING","input_binding_ids":"STRING[]","input_revision_ids":"STRING[]","model_version":"STRING","rule_version":"STRING","state":"STRING","view_kind":"STRING","workspace_id":"STRING"},"EvidenceSpan":{"id":"STRING","identity_key":"STRING","locator_json":"STRING","locator_kind":"STRING","policy_id":"STRING","revision_id":"STRING","text":"STRING","text_hash":"STRING"},"Generation":{"coverage_json":"STRING","created_at":"TIMESTAMP","embedding_profile":"STRING","id":"STRING","identity_key":"STRING","linker_version":"STRING","manifest_hash":"STRING","parent_id":"STRING","parser_version":"STRING","published_at":"TIMESTAMP","source_id":"STRING","status":"STRING"},"GenerationMember":{"artifact_revision_id":"STRING","generation_id":"STRING","id":"STRING","identity_key":"STRING"},"GroupMembership":{"enabled":"BOOLEAN","group_id":"STRING","id":"STRING","identity_key":"STRING","mapping_authority":"STRING","policy_epoch":"INT64","principal_id":"STRING","workspace_id":"STRING"},"HistoryManifest":{"assertion_version_ids":"STRING[]","coverage_json":"STRING","id":"STRING","identity_key":"STRING","knowledge_cutoff":"TIMESTAMP","link_generation_ids":"STRING[]","retention_gaps":"STRING[]","revision_ids":"STRING[]","temporal_selector_json":"STRING","workspace_id":"STRING"},"IndexEvent":{"aggregate_id":"STRING","created_at":"TIMESTAMP","dedupe_key":"STRING","generation_id":"STRING","id":"STRING","identity_key":"STRING","kind":"STRING","payload_json":"STRING","sequence":"INT64","state":"STRING","workspace_id":"STRING"},"IndexManifest":{"checksums":"STRING","config_fingerprint":"STRING","generation_id":"STRING","id":"STRING","identity_key":"STRING","missing_optional":"STRING[]","profile_fingerprint":"STRING","ready":"BOOLEAN","required_representations":"STRING[]"},"KnowledgeObject":{"canonical_key":"STRING","id":"STRING","identity_key":"STRING","kind":"STRING","workspace_id":"STRING"},"LinkGeneration":{"assertion_version_ids":"STRING[]","coverage_json":"STRING","created_at":"TIMESTAMP","id":"STRING","identity_key":"STRING","input_manifest_hash":"STRING","linker_version":"STRING","workspace_id":"STRING"},"MaintenanceJob":{"attempt_count":"INT64","cursor_json":"STRING","error_code":"STRING","expected_parent_id":"STRING","fencing_token":"INT64","id":"STRING","identity_key":"STRING","input_fingerprint":"STRING","job_key":"STRING","kind":"STRING","lease_expires_at":"TIMESTAMP","lease_owner":"STRING","phase":"STRING","retry_at":"TIMESTAMP","scope_key":"STRING","source_id":"STRING","status":"STRING"},"NativeBinding":{"generation_id":"STRING","id":"STRING","identity_key":"STRING","native_id":"STRING","native_kind":"STRING","object_id":"STRING","span_id":"STRING"},"ObjectObservation":{"attributes_json":"STRING","evidence_class":"STRING","id":"STRING","identity_key":"STRING","object_id":"STRING","recorded_from":"TIMESTAMP","recorded_to":"TIMESTAMP","revision_id":"STRING","source_timestamp_original":"STRING","source_timezone":"STRING","span_id":"STRING","temporal_basis":"STRING","temporal_precision":"STRING","valid_from":"TIMESTAMP","valid_to":"TIMESTAMP","validity_kind":"STRING"},"PurgeJob":{"audit_code":"STRING","backup_disposition":"STRING","completed_at":"TIMESTAMP","created_at":"TIMESTAMP","derived_status":"STRING","id":"STRING","identity_key":"STRING","phase":"STRING","raw_status":"STRING","removal_manifest_ids":"STRING[]","request_key":"STRING","saved_output_status":"STRING","scope_key":"STRING","workspace_id":"STRING"},"QuerySnapshot":{"created_at":"TIMESTAMP","history_manifest_ids":"STRING[]","id":"STRING","identity_key":"STRING","knowledge_cutoff":"TIMESTAMP","link_generation_id":"STRING","policy_fingerprint":"STRING","profile_fingerprint":"STRING","settings_fingerprint":"STRING","sources":"STRING","suppression_epoch":"INT64","temporal":"STRING","workspace_id":"STRING"},"RetrievalView":{"dependency_fingerprint":"STRING","derivation_version":"STRING","derived_record_id":"STRING","id":"STRING","identity_key":"STRING","object_id":"STRING","source_revision_id":"STRING","span_id":"STRING","text":"STRING","text_profile":"STRING","vector_profile":"STRING","view_kind":"STRING"},"Section":{"breadcrumb":"STRING[]","id":"STRING","identity_key":"STRING","ordinal":"INT64","original_heading":"STRING","original_span_ids":"STRING[]","parent_section_id":"STRING","source_revision_id":"STRING"},"SectionMember":{"child_id":"STRING","child_kind":"STRING","id":"STRING","identity_key":"STRING","ordinal":"INT64","section_id":"STRING"},"SourceEvent":{"acceptance_state":"STRING","artifact_id":"STRING","connector_id":"STRING","dedupe_key":"STRING","delivery_id":"STRING","id":"STRING","identity_key":"STRING","operation":"STRING","payload_hash":"STRING","provider_artifact_id":"STRING","provider_instance":"STRING","provider_revision":"STRING","provider_sequence":"STRING","received_at":"TIMESTAMP"},"Suppression":{"all_principals":"BOOLEAN","created_at":"TIMESTAMP","epoch":"INT64","id":"STRING","identity_key":"STRING","principal_ids":"STRING[]","reason":"STRING","restoration_barrier":"STRING","scope_key":"STRING","target_id":"STRING","target_kind":"STRING","view_applicability":"STRING","workspace_id":"STRING"},"SyncRun":{"attempt_count":"INT64","connector_id":"STRING","cursor_json":"STRING","error_code":"STRING","expected_parent_id":"STRING","fencing_token":"INT64","id":"STRING","identity_key":"STRING","input_fingerprint":"STRING","lease_expires_at":"TIMESTAMP","lease_owner":"STRING","phase":"STRING","retry_at":"TIMESTAMP","run_key":"STRING","scope_key":"STRING","source_id":"STRING","status":"STRING"},"SyncState":{"connector_id":"STRING","cursor_json":"STRING","error_code":"STRING","id":"STRING","identity_key":"STRING","last_reconciled_at":"TIMESTAMP","last_success_at":"TIMESTAMP","partition_key":"STRING","watermark":"STRING"},"Workspace":{"id":"STRING","identity_key":"STRING","name":"STRING"},"WorkspaceMembership":{"enabled":"BOOLEAN","id":"STRING","identity_key":"STRING","mapping_authority":"STRING","policy_epoch":"INT64","principal_id":"STRING","workspace_id":"STRING"}},[["SUBJECT_OBJECT","Assertion","KnowledgeObject"],["TARGET_OBJECT","Assertion","KnowledgeObject"],["VERSION_OF","AssertionVersion","Assertion"],["SUPPORT_VERSION","AssertionSupport","AssertionVersion"],["SUPPORT_SPAN","AssertionSupport","EvidenceSpan"],["REVISION_OF","ArtifactRevision","Artifact"],["SPAN_REVISION","EvidenceSpan","ArtifactRevision"],["OBSERVED_OBJECT","ObjectObservation","KnowledgeObject"],["OBSERVATION_SPAN","ObjectObservation","EvidenceSpan"],["MEMBER_GENERATION","GenerationMember","Generation"],["MEMBER_REVISION","GenerationMember","ArtifactRevision"],["BINDING_OBJECT","NativeBinding","KnowledgeObject"],["BINDING_SPAN","NativeBinding","EvidenceSpan"],["SECTION_PARENT","SectionMember","Section"]],{"active_generation_id":"STRING","generation_lock":"INT64","generation_version":"INT64","workspace_id":"STRING"},{"artifact_revision_id":"STRING","content_kind":"STRING","embedding_profile":"STRING","generation_id":"STRING","parent_passage_id":"STRING","span_id":"STRING"}]'
)
V3_CHECKSUM = "ffc12b6f274a5b5573eed4dde9798f8b4abe9d37d68a570247a5c281c10d3ddc"

V4_DESCRIPTOR = json.loads(
    '[4,{"AccessPolicy":{"allow_groups":"STRING[]","allow_users":"STRING[]","deny_groups":"STRING[]","deny_users":"STRING[]","expires_at":"TIMESTAMP","id":"STRING","identity_key":"STRING","mode":"STRING","origin":"STRING","scope_key":"STRING","verified_at":"TIMESTAMP","workspace_id":"STRING"},"Alias":{"alias_key":"STRING","authority":"STRING","id":"STRING","identity_key":"STRING","namespace":"STRING","status":"STRING","support_span_ids":"STRING[]","target_object_id":"STRING","workspace_id":"STRING"},"Artifact":{"canonical_uri":"STRING","connector_id":"STRING","deleted_at":"TIMESTAMP","external_id":"STRING","id":"STRING","identity_key":"STRING","kind":"STRING","policy_id":"STRING","provider_instance":"STRING","source_id":"STRING","workspace_id":"STRING"},"ArtifactRevision":{"artifact_id":"STRING","content_hash":"STRING","id":"STRING","identity_key":"STRING","lifecycle":"STRING","metadata_json":"STRING","observed_at":"TIMESTAMP","provider_revision":"STRING","raw_uri":"STRING","source_precision":"STRING","source_timestamp_original":"STRING","source_timezone":"STRING","source_updated_at":"TIMESTAMP"},"Assertion":{"id":"STRING","identity_key":"STRING","object_id":"STRING","predicate":"STRING","scope_key":"STRING","subject_id":"STRING","workspace_id":"STRING"},"AssertionSupport":{"assertion_version_id":"STRING","derivation_group":"STRING","id":"STRING","identity_key":"STRING","span_id":"STRING"},"AssertionVersion":{"assertion_id":"STRING","confidence":"DOUBLE","evidence_class":"STRING","id":"STRING","identity_key":"STRING","recorded_from":"TIMESTAMP","recorded_to":"TIMESTAMP","rule_version":"STRING","source_timestamp_original":"STRING","source_timezone":"STRING","status":"STRING","temporal_basis":"STRING","temporal_precision":"STRING","valid_from":"TIMESTAMP","valid_to":"TIMESTAMP","validity_kind":"STRING"},"ConflictSet":{"assertion_version_ids":"STRING[]","id":"STRING","identity_key":"STRING","resolution_rule":"STRING","resolution_status":"STRING","scope_key":"STRING","support_span_ids":"STRING[]","valid_from":"TIMESTAMP","valid_to":"TIMESTAMP","workspace_id":"STRING"},"Connector":{"capabilities_json":"STRING","config_json":"STRING","credential_ref":"STRING","enabled":"BOOLEAN","id":"STRING","identity_key":"STRING","instance_url":"STRING","kind":"STRING","workspace_id":"STRING"},"ConsumerAck":{"acknowledged_at":"TIMESTAMP","attempt_count":"INT64","consumer_id":"STRING","event_id":"STRING","fencing_token":"INT64","id":"STRING","identity_key":"STRING","lease_expires_at":"TIMESTAMP","lease_owner":"STRING","retry_at":"TIMESTAMP","state":"STRING"},"DerivedDependency":{"derived_record_id":"STRING","id":"STRING","identity_key":"STRING","input_id":"STRING","input_kind":"STRING","input_version":"STRING"},"DerivedRecord":{"dependency_fingerprint":"STRING","id":"STRING","identity_key":"STRING","input_binding_ids":"STRING[]","input_revision_ids":"STRING[]","model_version":"STRING","rule_version":"STRING","state":"STRING","view_kind":"STRING","workspace_id":"STRING"},"EvidenceSpan":{"id":"STRING","identity_key":"STRING","locator_json":"STRING","locator_kind":"STRING","policy_id":"STRING","revision_id":"STRING","text":"STRING","text_hash":"STRING"},"Generation":{"coverage_json":"STRING","created_at":"TIMESTAMP","embedding_profile":"STRING","id":"STRING","identity_key":"STRING","linker_version":"STRING","manifest_hash":"STRING","parent_id":"STRING","parser_version":"STRING","published_at":"TIMESTAMP","source_id":"STRING","status":"STRING"},"GenerationEvidenceMember":{"generation_id":"STRING","id":"STRING","identity_key":"STRING","record_id":"STRING","record_kind":"STRING"},"GenerationMember":{"artifact_revision_id":"STRING","generation_id":"STRING","id":"STRING","identity_key":"STRING"},"GroupMembership":{"enabled":"BOOLEAN","group_id":"STRING","id":"STRING","identity_key":"STRING","mapping_authority":"STRING","policy_epoch":"INT64","principal_id":"STRING","workspace_id":"STRING"},"HistoryManifest":{"assertion_version_ids":"STRING[]","coverage_json":"STRING","id":"STRING","identity_key":"STRING","knowledge_cutoff":"TIMESTAMP","link_generation_ids":"STRING[]","retention_gaps":"STRING[]","revision_ids":"STRING[]","temporal_selector_json":"STRING","workspace_id":"STRING"},"IndexEvent":{"aggregate_id":"STRING","created_at":"TIMESTAMP","dedupe_key":"STRING","generation_id":"STRING","id":"STRING","identity_key":"STRING","kind":"STRING","payload_json":"STRING","sequence":"INT64","state":"STRING","workspace_id":"STRING"},"IndexManifest":{"checksums":"STRING","config_fingerprint":"STRING","generation_id":"STRING","id":"STRING","identity_key":"STRING","missing_optional":"STRING[]","profile_fingerprint":"STRING","ready":"BOOLEAN","required_representations":"STRING[]"},"KnowledgeObject":{"canonical_key":"STRING","id":"STRING","identity_key":"STRING","kind":"STRING","workspace_id":"STRING"},"LinkGeneration":{"assertion_version_ids":"STRING[]","coverage_json":"STRING","created_at":"TIMESTAMP","id":"STRING","identity_key":"STRING","input_manifest_hash":"STRING","linker_version":"STRING","workspace_id":"STRING"},"MaintenanceJob":{"attempt_count":"INT64","cursor_json":"STRING","error_code":"STRING","expected_parent_id":"STRING","fencing_token":"INT64","id":"STRING","identity_key":"STRING","input_fingerprint":"STRING","job_key":"STRING","kind":"STRING","lease_expires_at":"TIMESTAMP","lease_owner":"STRING","phase":"STRING","retry_at":"TIMESTAMP","scope_key":"STRING","source_id":"STRING","status":"STRING"},"NativeBinding":{"generation_id":"STRING","id":"STRING","identity_key":"STRING","native_id":"STRING","native_kind":"STRING","object_id":"STRING","span_id":"STRING"},"ObjectObservation":{"attributes_json":"STRING","evidence_class":"STRING","id":"STRING","identity_key":"STRING","object_id":"STRING","recorded_from":"TIMESTAMP","recorded_to":"TIMESTAMP","revision_id":"STRING","source_timestamp_original":"STRING","source_timezone":"STRING","span_id":"STRING","temporal_basis":"STRING","temporal_precision":"STRING","valid_from":"TIMESTAMP","valid_to":"TIMESTAMP","validity_kind":"STRING"},"PurgeJob":{"audit_code":"STRING","backup_disposition":"STRING","completed_at":"TIMESTAMP","created_at":"TIMESTAMP","derived_status":"STRING","id":"STRING","identity_key":"STRING","phase":"STRING","raw_status":"STRING","removal_manifest_ids":"STRING[]","request_key":"STRING","saved_output_status":"STRING","scope_key":"STRING","workspace_id":"STRING"},"QuerySnapshot":{"created_at":"TIMESTAMP","history_manifest_ids":"STRING[]","id":"STRING","identity_key":"STRING","knowledge_cutoff":"TIMESTAMP","link_generation_id":"STRING","policy_fingerprint":"STRING","profile_fingerprint":"STRING","settings_fingerprint":"STRING","sources":"STRING","suppression_epoch":"INT64","temporal":"STRING","workspace_id":"STRING"},"RetrievalView":{"dependency_fingerprint":"STRING","derivation_version":"STRING","derived_record_id":"STRING","id":"STRING","identity_key":"STRING","object_id":"STRING","source_revision_id":"STRING","span_id":"STRING","text":"STRING","text_profile":"STRING","vector_profile":"STRING","view_kind":"STRING"},"Section":{"breadcrumb":"STRING[]","id":"STRING","identity_key":"STRING","ordinal":"INT64","original_heading":"STRING","original_span_ids":"STRING[]","parent_section_id":"STRING","source_revision_id":"STRING"},"SectionMember":{"child_id":"STRING","child_kind":"STRING","id":"STRING","identity_key":"STRING","ordinal":"INT64","section_id":"STRING"},"SnapshotReference":{"created_at":"TIMESTAMP","id":"STRING","identity_key":"STRING","kind":"STRING","lease_expires_at":"TIMESTAMP","lease_owner":"STRING","reference_key":"STRING","released_at":"TIMESTAMP","snapshot_id":"STRING","workspace_id":"STRING"},"SourceEvent":{"acceptance_state":"STRING","artifact_id":"STRING","connector_id":"STRING","dedupe_key":"STRING","delivery_id":"STRING","id":"STRING","identity_key":"STRING","operation":"STRING","payload_hash":"STRING","provider_artifact_id":"STRING","provider_instance":"STRING","provider_revision":"STRING","provider_sequence":"STRING","received_at":"TIMESTAMP"},"Suppression":{"all_principals":"BOOLEAN","created_at":"TIMESTAMP","epoch":"INT64","id":"STRING","identity_key":"STRING","principal_ids":"STRING[]","reason":"STRING","restoration_barrier":"STRING","scope_key":"STRING","target_id":"STRING","target_kind":"STRING","view_applicability":"STRING","workspace_id":"STRING"},"SyncRun":{"attempt_count":"INT64","connector_id":"STRING","cursor_json":"STRING","error_code":"STRING","expected_parent_id":"STRING","fencing_token":"INT64","id":"STRING","identity_key":"STRING","input_fingerprint":"STRING","lease_expires_at":"TIMESTAMP","lease_owner":"STRING","phase":"STRING","retry_at":"TIMESTAMP","run_key":"STRING","scope_key":"STRING","source_id":"STRING","status":"STRING"},"SyncState":{"connector_id":"STRING","cursor_json":"STRING","error_code":"STRING","id":"STRING","identity_key":"STRING","last_reconciled_at":"TIMESTAMP","last_success_at":"TIMESTAMP","partition_key":"STRING","watermark":"STRING"},"Workspace":{"id":"STRING","identity_key":"STRING","name":"STRING"},"WorkspaceMembership":{"enabled":"BOOLEAN","id":"STRING","identity_key":"STRING","mapping_authority":"STRING","policy_epoch":"INT64","principal_id":"STRING","workspace_id":"STRING"}},[["SUBJECT_OBJECT","Assertion","KnowledgeObject"],["TARGET_OBJECT","Assertion","KnowledgeObject"],["VERSION_OF","AssertionVersion","Assertion"],["SUPPORT_VERSION","AssertionSupport","AssertionVersion"],["SUPPORT_SPAN","AssertionSupport","EvidenceSpan"],["REVISION_OF","ArtifactRevision","Artifact"],["SPAN_REVISION","EvidenceSpan","ArtifactRevision"],["OBSERVED_OBJECT","ObjectObservation","KnowledgeObject"],["OBSERVATION_SPAN","ObjectObservation","EvidenceSpan"],["MEMBER_GENERATION","GenerationMember","Generation"],["MEMBER_REVISION","GenerationMember","ArtifactRevision"],["BINDING_OBJECT","NativeBinding","KnowledgeObject"],["BINDING_SPAN","NativeBinding","EvidenceSpan"],["SECTION_PARENT","SectionMember","Section"],["EVIDENCE_GENERATION","GenerationEvidenceMember","Generation"],["REFERENCE_SNAPSHOT","SnapshotReference","QuerySnapshot"]],{"active_build_id":"STRING","active_generation_id":"STRING","build_fencing_token":"INT64","generation_lock":"INT64","generation_version":"INT64","managed":"BOOLEAN","workspace_id":"STRING"},{"artifact_revision_id":"STRING","content_kind":"STRING","embedding_profile":"STRING","generation_id":"STRING","parent_passage_id":"STRING","span_id":"STRING"},{"Commit":{"generation_id":"STRING"},"DataObject":{"generation_id":"STRING"},"Symbol":{"generation_id":"STRING"}}]'
)
V4_CHECKSUM = "af3234c2ffd6aa2a5c935b06352ad91c92b8c44f80926969a6c3a775a4d5dfd7"

DEFAULT_WORKSPACE = Workspace(name="default")
DEFAULT_WORKSPACE_ID = DEFAULT_WORKSPACE.id


def plain_annotation(annotation):
    if get_origin(annotation) is Annotated:
        return plain_annotation(get_args(annotation)[0])
    if get_origin(annotation) in (Union, types.UnionType):
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(members) == 1:
            return plain_annotation(members[0])
    return annotation


def _type(annotation) -> str:
    annotation = plain_annotation(annotation)
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        return _type(members[0]) if len(members) == 1 else "STRING"
    if origin is Literal:
        return _type(type(get_args(annotation)[0]))
    if annotation is bool:
        return "BOOLEAN"
    if annotation is int:
        return "INT64"
    if annotation is float:
        return "DOUBLE"
    if annotation is datetime:
        return "TIMESTAMP"
    if origin is tuple and plain_annotation(get_args(annotation)[0]) is str:
        return "STRING[]"
    return "STRING"


KNOWLEDGE_COLUMNS = {
    name: {field: _type(info.annotation) for field, info in model.model_fields.items()}
    for name, model in RECORD_TYPES.items()
}
# Explicit graph endpoints mirror scalar references. Membership paths remain typed.
KNOWLEDGE_RELATIONS = [
    ("SUBJECT_OBJECT", "Assertion", "KnowledgeObject"),
    ("TARGET_OBJECT", "Assertion", "KnowledgeObject"),
    ("VERSION_OF", "AssertionVersion", "Assertion"),
    ("SUPPORT_VERSION", "AssertionSupport", "AssertionVersion"),
    ("SUPPORT_SPAN", "AssertionSupport", "EvidenceSpan"),
    ("REVISION_OF", "ArtifactRevision", "Artifact"),
    ("SPAN_REVISION", "EvidenceSpan", "ArtifactRevision"),
    ("OBSERVED_OBJECT", "ObjectObservation", "KnowledgeObject"),
    ("OBSERVATION_SPAN", "ObjectObservation", "EvidenceSpan"),
    ("MEMBER_GENERATION", "GenerationMember", "Generation"),
    ("MEMBER_REVISION", "GenerationMember", "ArtifactRevision"),
    ("BINDING_OBJECT", "NativeBinding", "KnowledgeObject"),
    ("BINDING_SPAN", "NativeBinding", "EvidenceSpan"),
    ("SECTION_PARENT", "SectionMember", "Section"),
    ("EVIDENCE_GENERATION", "GenerationEvidenceMember", "Generation"),
    ("REFERENCE_SNAPSHOT", "SnapshotReference", "QuerySnapshot"),
]
SOURCE_COLUMNS = {
    "workspace_id": "STRING",
    "active_generation_id": "STRING",
    "generation_version": "INT64",
    "generation_lock": "INT64",
    "managed": "BOOLEAN",
    "active_build_id": "STRING",
    "build_fencing_token": "INT64",
}
PASSAGE_COLUMNS = {
    "retrieval_view_id": "STRING",
    "generation_id": "STRING",
    "artifact_revision_id": "STRING",
    "span_id": "STRING",
    "parent_passage_id": "STRING",
    "content_kind": "STRING",
    "embedding_profile": "STRING",
}
NATIVE_COLUMNS = {name: {"generation_id": "STRING"} for name in ("Symbol", "DataObject", "Commit")}
V1_CHECKSUM = text_hash("hippo-legacy-schema-v1")
MIGRATION_CHECKSUM = text_hash(
    canonical_json(
        [
            CURRENT_SCHEMA_VERSION,
            KNOWLEDGE_COLUMNS,
            KNOWLEDGE_RELATIONS,
            SOURCE_COLUMNS,
            PASSAGE_COLUMNS,
            NATIVE_COLUMNS,
        ]
    )
)
SUPPORTED_CHECKSUMS = {1: V1_CHECKSUM, 2: V2_CHECKSUM, 3: V3_CHECKSUM, 4: V4_CHECKSUM, 5: MIGRATION_CHECKSUM}


def _descriptor(version):
    if version == 2:
        return V2_DESCRIPTOR
    if version == 3:
        return V3_DESCRIPTOR
    if version == 4:
        return V4_DESCRIPTOR
    if version == 5:
        return [5, KNOWLEDGE_COLUMNS, KNOWLEDGE_RELATIONS, SOURCE_COLUMNS, PASSAGE_COLUMNS, NATIVE_COLUMNS]
    raise SchemaCompatibilityError("Unsupported migration version")


class SchemaCompatibilityError(RuntimeError):
    pass


def schema_version(store) -> dict | None:
    if store.knowledge_backend == "fake":
        return getattr(store, "_schema_row", None)
    if store.knowledge_backend == "ladybug":
        if not store.run("CALL show_tables() WHERE name = 'SchemaVersion' RETURN name, type"):
            return None
    rows = store.run(
        "MATCH (v:SchemaVersion) RETURN v.version AS version, v.checksum AS checksum, v.state AS state, v.step AS step ORDER BY v.version DESC"
    )
    return rows[0] if rows else None


def check_compatibility(store) -> dict | None:
    row = schema_version(store)
    if row is None:
        if _has_managed_schema(store):
            raise SchemaCompatibilityError("Evidence schema has no migration history; store was not modified")
        return None
    if row and (
        type(row["version"]) is not int
        or row["version"] not in SUPPORTED_CHECKSUMS
        or row["checksum"] != SUPPORTED_CHECKSUMS.get(row["version"])
    ):
        raise SchemaCompatibilityError(
            "Unsupported schema version or migration checksum; store was not modified"
        )
    if row:
        history = schema_history(store)
        for historical in history:
            if type(historical["version"]) is not int or historical["checksum"] != SUPPORTED_CHECKSUMS.get(
                historical["version"]
            ):
                raise SchemaCompatibilityError(
                    "Unsupported historical migration checksum; store was not modified"
                )
            version, state, step = historical["version"], historical["state"], historical["step"]
            expected = (
                0
                if version == 1 or store.knowledge_backend == "fake"
                else len(schema_steps(store, version=version))
            )
            if (
                type(state) is not str
                or state not in {"complete", "pending"}
                or type(step) is not int
                or not 0 <= step <= expected
                or (state == "complete" and step != expected)
                or (version < row["version"] and state != "complete")
                or (version == 1 and state != "complete")
            ):
                raise SchemaCompatibilityError(
                    "Invalid migration journal state or step; store was not modified"
                )
        if [item["version"] for item in history] != list(range(1, row["version"] + 1)) or history[-1] != row:
            raise SchemaCompatibilityError(
                "Migration history is incomplete or inconsistent; store was not modified"
            )
    return row


def _has_managed_schema(store):
    """Only a real legacy installation may start without a version journal."""
    if store.knowledge_backend == "fake":
        return bool(store._schema_history or store._knowledge_data)
    if store.knowledge_backend == "ladybug":
        return any(row["name"] in KNOWLEDGE_COLUMNS for row in store.run("CALL show_tables() RETURN name"))
    constraints = store.run("SHOW CONSTRAINTS YIELD labelsOrTypes RETURN labelsOrTypes")
    if any(set(row["labelsOrTypes"]) & KNOWLEDGE_COLUMNS.keys() for row in constraints):
        return True
    return bool(
        store.run(
            "MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) RETURN n LIMIT 1",
            labels=list(KNOWLEDGE_COLUMNS),
        )
    )


def schema_history(store) -> list[dict]:
    if store.knowledge_backend == "fake":
        return [dict(row) for _, row in sorted(store._schema_history.items())]
    return store.run(
        "MATCH (v:SchemaVersion) RETURN v.version AS version, v.checksum AS checksum, v.state AS state, v.step AS step ORDER BY v.version"
    )


def _record_legacy_version(store) -> None:
    row = {"version": 1, "checksum": V1_CHECKSUM, "state": "complete", "step": 0}
    if store.knowledge_backend == "fake":
        store._schema_history.setdefault(1, row)
    elif not store.run("MATCH (v:SchemaVersion {version:1}) RETURN v.id AS id"):
        store.run(
            "CREATE (:SchemaVersion {id:'knowledge-v1',version:1,checksum:$checksum,state:'complete',step:0})",
            checksum=V1_CHECKSUM,
        )


def validate_existing_legacy_shape(store) -> None:
    """Missing old tables can be added, but existing incompatible columns cannot."""
    if store.knowledge_backend != "ladybug":
        return
    from .ladybug import NODE_TABLES

    existing = {row["name"] for row in store.run("CALL show_tables() RETURN name")}
    for name, declaration in NODE_TABLES.items():
        if name not in existing:
            continue
        actual = {row["name"]: row for row in store.run(f"CALL table_info('{name}') RETURN *")}
        for column in declaration.split(","):
            field, kind, *_ = column.split()
            if field not in actual or actual[field]["type"] != {"BOOLEAN": "BOOL"}.get(kind, kind):
                raise SchemaCompatibilityError("Legacy schema shape has an absent or incompatible column")
            if "PRIMARY KEY" in column and not actual[field]["primary key"]:
                raise SchemaCompatibilityError("Legacy schema shape lacks its declared primary key")


def validate_physical_schema(store, *, version=CURRENT_SCHEMA_VERSION) -> None:
    """A completion record cannot substitute for the actual schema declarations."""
    if store.knowledge_backend == "fake":
        return
    _, knowledge_columns, knowledge_relations, source_columns, passage_columns = _descriptor(version)[:5]
    if store.knowledge_backend == "ladybug":
        tables = {row["name"]: row["type"] for row in store.run("CALL show_tables() RETURN name,type")}
        for name, columns in {
            **knowledge_columns,
            "Source": source_columns,
            "Passage": passage_columns,
            **(
                {name: {"generation_id": "STRING"} for name in ("Symbol", "DataObject", "Commit")}
                if version >= 4
                else {}
            ),
        }.items():
            if tables.get(name) != "NODE":
                raise SchemaCompatibilityError("Evidence schema shape is missing a node table")
            actual = {row["name"]: row for row in store.run(f"CALL table_info('{name}') RETURN *")}
            for field, kind in columns.items():
                if field not in actual or actual[field]["type"] != {"BOOLEAN": "BOOL"}.get(kind, kind):
                    raise SchemaCompatibilityError(
                        "Evidence schema shape has an absent or incompatible column"
                    )
            if name in knowledge_columns and not actual["id"]["primary key"]:
                raise SchemaCompatibilityError("Evidence schema shape lacks its primary key")
        for name, source, target in knowledge_relations:
            if tables.get(name) != "REL" or store.connection_pairs(name) != {(source, target)}:
                raise SchemaCompatibilityError(
                    "Evidence schema shape has incompatible relationship endpoints"
                )
        return
    constraints = {
        row["name"]: row
        for row in store.run(
            "SHOW CONSTRAINTS YIELD name,labelsOrTypes,properties,type RETURN name,labelsOrTypes,properties,type"
        )
    }
    for name in knowledge_columns:
        found = constraints.get(f"knowledge_{name.lower()}_id")
        if (
            found is None
            or found["labelsOrTypes"] != [name]
            or found["properties"] != ["id"]
            or found["type"] != "UNIQUENESS"
        ):
            raise SchemaCompatibilityError(
                "Evidence schema shape has an absent or incompatible uniqueness constraint"
            )
    indexes = {
        row["name"]: row
        for row in store.run(
            "SHOW INDEXES YIELD name,labelsOrTypes,properties,type RETURN name,labelsOrTypes,properties,type"
        )
    }
    for name, columns in knowledge_columns.items():
        for field in columns.keys() & {
            "workspace_id",
            "artifact_id",
            "revision_id",
            "generation_id",
            "predicate",
            "subject_id",
            "object_id",
            "recorded_from",
            "valid_from",
        }:
            found = indexes.get(f"knowledge_{name.lower()}_{field}")
            if (
                found is None
                or found["labelsOrTypes"] != [name]
                or found["properties"] != [field]
                or found["type"] != "RANGE"
            ):
                raise SchemaCompatibilityError(
                    "Evidence schema shape has an absent or incompatible lookup index"
                )


def _version(store, state: str, step: int, *, version=CURRENT_SCHEMA_VERSION) -> None:
    row = {"version": version, "checksum": SUPPORTED_CHECKSUMS[version], "state": state, "step": step}
    if store.knowledge_backend == "fake":
        store._schema_row = row
        store._schema_history[version] = dict(row)
        return
    store.run(
        "MERGE (v:SchemaVersion {id: $id}) SET v.version=$version, v.checksum=$checksum, v.state=$state, v.step=$step",
        id=f"knowledge-v{version}",
        **row,
    )


def schema_steps(store, *, version=CURRENT_SCHEMA_VERSION) -> list[str]:
    if version == 3:
        return (
            [
                "ALTER TABLE AccessPolicy ADD IF NOT EXISTS origin STRING",
                "ALTER TABLE AccessPolicy ADD IF NOT EXISTS scope_key STRING",
            ]
            if store.knowledge_backend == "ladybug"
            else []
        )
    _, knowledge_columns, knowledge_relations, source_columns, passage_columns = _descriptor(version)[:5]
    if store.knowledge_backend == "ladybug":
        steps = [
            f"CREATE NODE TABLE IF NOT EXISTS {name}("
            + ", ".join(
                f"{field} {kind}" + (" PRIMARY KEY" if field == "id" else "")
                for field, kind in columns.items()
            )
            + ")"
            for name, columns in knowledge_columns.items()
        ]
        steps += [
            f"CREATE REL TABLE IF NOT EXISTS {name}(FROM {source} TO {target})"
            for name, source, target in knowledge_relations
        ]
        steps += [
            f"ALTER TABLE {table} ADD IF NOT EXISTS {field} {kind}"
            for table, columns in (("Source", source_columns), ("Passage", passage_columns))
            for field, kind in columns.items()
        ]
        if version >= 4:
            steps += [
                f"ALTER TABLE {name} ADD IF NOT EXISTS generation_id STRING"
                for name in ("Symbol", "DataObject", "Commit")
            ]
        return steps
    return [
        f"CREATE CONSTRAINT knowledge_{name.lower()}_id IF NOT EXISTS FOR (n:{name}) REQUIRE n.id IS UNIQUE"
        for name in knowledge_columns
    ] + [
        f"CREATE INDEX knowledge_{name.lower()}_{field} IF NOT EXISTS FOR (n:{name}) ON (n.{field})"
        for name, columns in knowledge_columns.items()
        for field in columns
        if field
        in {
            "workspace_id",
            "artifact_id",
            "revision_id",
            "generation_id",
            "predicate",
            "subject_id",
            "object_id",
            "recorded_from",
            "valid_from",
        }
    ]


def _data_transform(store, *, version=CURRENT_SCHEMA_VERSION):
    if version == 5:
        return
    if version == 4:
        managed = {r.source_id for name in ("Artifact", "Generation") for r in store._knowledge_rows(name)}
        if store.knowledge_backend == "fake":
            for source in store.sources.values():
                source["managed"] = bool(source.get("managed")) or source["id"] in managed
                source.setdefault("active_build_id", None)
                source.setdefault("build_fencing_token", 0)
        else:
            store.run(
                "MATCH (s:Source) SET s.managed=coalesce(s.managed,false), s.build_fencing_token=coalesce(s.build_fencing_token,0)"
            )
            for source_id in managed:
                store.run("MATCH (s:Source {id:$id}) SET s.managed=true", id=source_id)
        for key in ("content_epoch", "suppression_epoch"):
            if store.get_meta(key) is None:
                store.set_meta(
                    key, len(store._knowledge_rows("Suppression")) if key == "suppression_epoch" else 0
                )
        return
    if version == 3:
        if store.knowledge_backend != "fake":
            store.run("MATCH (p:AccessPolicy) WHERE p.origin IS NULL SET p.origin='legacy_unknown'")
        # Reading validates canonical identities, including partially populated rows;
        # a failed transform rolls back instead of declaring malformed evidence ready.
        store._knowledge_rows("AccessPolicy")
        return
    store._write_knowledge(DEFAULT_WORKSPACE)
    if store.knowledge_backend == "fake":
        for source in store.sources.values():
            source.setdefault("workspace_id", DEFAULT_WORKSPACE_ID)
            source.setdefault("active_generation_id", None)
            source.setdefault("generation_version", 0)
        return
    store.run(
        "MATCH (s:Source) SET s.workspace_id=coalesce(s.workspace_id,$workspace), s.generation_version=coalesce(s.generation_version,0), s.generation_lock=coalesce(s.generation_lock,0)",
        workspace=DEFAULT_WORKSPACE_ID,
    )


def migrate_store(store, *, fault_hook=None) -> None:
    # A readiness exception must not prevent this internal recovery path.
    with store._lock:
        store._migrating = True
        try:
            store._migration_blocked = True
            prior = check_compatibility(store)
            validate_existing_legacy_shape(store)
            if prior and prior["version"] >= 2 and prior["state"] == "complete":
                validate_physical_schema(store, version=prior["version"])
            if prior and prior["version"] == CURRENT_SCHEMA_VERSION and prior["state"] == "complete":
                store._migration_blocked = False
                store._schema_checked = True
                return
            start = prior["version"] + (prior["state"] == "complete") if prior else 2
            versions = range(max(2, start), CURRENT_SCHEMA_VERSION + 1)

            def apply_version(version):
                steps = schema_steps(store, version=version)
                for index, statement in enumerate(steps):
                    store.run(statement)
                    if store.knowledge_backend == "neo4j":
                        _version(store, "pending", index + 1, version=version)
                    if fault_hook:
                        fault_hook(f"schema:{index}")
                validate_physical_schema(store, version=version)
                return len(steps)

            def transform_version(version, step):
                _data_transform(store, version=version)
                if fault_hook:
                    fault_hook("data")
                _version(store, "complete", step, version=version)

            if store.knowledge_backend == "fake":
                with store.transaction():
                    _record_legacy_version(store)
                    for version in versions:
                        transform_version(version, 0)
            elif store.knowledge_backend == "ladybug":
                with store.transaction():
                    store._ensure_legacy_schema()
                    store.run(
                        "CREATE NODE TABLE IF NOT EXISTS SchemaVersion(id STRING PRIMARY KEY, version INT64, checksum STRING, state STRING, step INT64)"
                    )
                    _record_legacy_version(store)
                    for version in versions:
                        transform_version(version, apply_version(version))
            else:
                # Neo4j does not permit schema + data updates in one transaction.
                # Journal exists before each schema step; repeat IF NOT EXISTS on recovery.
                store.run(
                    "CREATE CONSTRAINT knowledge_schema_version IF NOT EXISTS FOR (n:SchemaVersion) REQUIRE n.id IS UNIQUE"
                )
                with store.transaction():
                    _record_legacy_version(store)
                    _version(store, "pending", 0, version=max(2, start))
                store._ensure_legacy_schema()
                for version in versions:
                    _version(store, "pending", 0, version=version)
                    step = apply_version(version)
                    with store.transaction():
                        transform_version(version, step)
            store._migration_blocked = False
            store._schema_checked = True
        finally:
            store._migrating = False

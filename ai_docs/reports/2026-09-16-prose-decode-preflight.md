# Prose decoding experiment: recovery pre-flight

The recovered plan is `ai_docs/plans/2026-09-16-prose-decode-plan.md`; the initial tree is `1ff6a37` plus its unfinished implementation and tests. The user authorized continued experiments and commits. Only Codex workers are permitted. Existing authorization/quality failures must be fixed, not hidden by a narrower benchmark.

Verdict: CLEAR for completing and testing this bounded experiment. Acceptance still requires independent review and a fresh-copy measured replay before commit.

- Wiring: `_knowledge_get` and `_knowledge_rows` continue to read storage, then call the instance `_knowledge_records`. Backend lock compatibility and all callers are explicit worker review requirements.
- Behavior: the existing validation path remains for misses, oversized rows and unsupported types; no failed validation is cached. Tests cover changed content and disappearance. The previous mutation of input row dictionaries is removed.
- Contracts: only deeply frozen ProseExtraction objects may be reused; response schema, durable IDs and authorization selection are unchanged. No API or route changes.
- Configuration: no settings, credentials, schema or dependency change. Read-only model requests for later replay use the existing local model with copied data; production services and original data stay untouched.
- Domain: explicit limits are 32 entries, 1 MiB per serialized key and 8 MiB aggregate keys. These are not claims of total process memory bounds.
- Credentials: none introduced or moved. No private evaluation contents will be committed.
- Gates: G1/G2 are existing local pytest commands, read and approved with the gate checker. G3 requires exact result/evidence comparison and measured runtime. Ownership is disjoint from the read-only quality extraction worker.

Recovery evidence: no live pytest, replay.py or profile_proof.py process was found in the process snapshot. Prior full-suite outcome is recorded in the recovered proof-performance results report; it does not verify this newer uncommitted experiment.

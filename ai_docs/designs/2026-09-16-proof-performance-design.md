# Evidence verification performance

The user authorized measured improvements, commits for successes, and rollback of failed experiments. The prior real-data round took 4,245.60 seconds for 12 questions; 9 answers were complete, 3 were deficient. An instrumented Q3 replay took 400.530 seconds, with 379.860 seconds inside repeated proof construction and 545,599 SQL calls (including startup). HTTP requests consumed 9.928 seconds. Private artifacts remain in `/private/tmp/hippo-real-eval-YCrJeD` and `/private/tmp/hippo-rag-research-qxBB5k`; never commit their content.

## Approach

First make each lineage verification cheaper without removing validation boundaries. Reuse records within one immutable generation inventory and share that inventory across selected views and prose during one proof. Never reuse it across separate proof builds. Preserve strict membership checks on every call even if a record was already loaded through a non-exact lookup. Do not cache complete authorization decisions or depend on epochs alone.

Alternatives: removing redundant validation wrappers has greater lifetime/revocation risk; changing models addresses only a small measured fraction. Defer both until this safer experiment is measured. Adaptive retrieval from Adaptive-RAG and typed evidence expansion inspired by EfficientRAG are later candidates, not part of this first slice.

## Preservation Analysis

### Behavioral Invariants
| # | Behavior | Location | Business Reason | Risk if Lost |
|---|---|---|---|---|
| 1 | Complete exact lineage before audience filtering | src/hippo/knowledge/access.py:242 | No private secondary inputs escape | Disclosure |
| 2 | Every validation rebuilds current proof | src/hippo/knowledge/access.py:679 | Detect mutations even without epoch change | Stale access |
| 3 | All dependency versions and membership checked | src/hippo/knowledge/derivations.py:143 | Reject corrupted or incomplete derivations | Unsupported evidence |

### Contract Surface
| Endpoint | Method | Auth | Request Shape | Response Shape | Status Codes |
|---|---|---|---|---|---|
| No external endpoint changes | unchanged | unchanged | unchanged | unchanged | unchanged |

### Domain Assumptions
| Value | Location | Why This Value | Impact if Changed |
|---|---|---|---|
| derived_evidence_version=1 | derivations.py:84 | Existing storage capability | No change |
| Per-inventory snapshot | derivations.py:252 | Existing generation immutability contract | Must not span writes |

### Wiring Map
| Interface | Implementation | Registration | Verified |
|---|---|---|---|
| Proof lineage | GenerationViews / _Inventory | _authorized_derivations | yes |
| Standalone validation | validate_view / validate_prose | fresh _Inventory per invocation | yes |

### Credential Source Inventory
| Credential | Runtime Source | Path/Key | Rotation? | Proxy/Cert Required | Verified in New Code |
|---|---|---|---|---|---|
| No changed credentials | local scratch Ladybug and existing Ollama | Config defaults | n/a | none locally | preserve |

### Failure Mode Analysis
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cached non-exact lookup bypasses exact membership | medium | high | Test both lookup orders |
| Mutated records survive across validation calls | medium | high | Fresh inventory per proof; corruption regression |
| Shared inventory crosses generation | low | high | Explicit generation check |
| Speed win masks changed answers | medium | high | Replay original corpus; inspect complete answers |

## Acceptance Gates

See `ai_docs/gates/proof-performance/GATES.md`. Success for this slice requires reduced duplicate reads, unchanged proof/security behavior, and measured query improvement. Overall goal additionally requires all 12 evaluation answers to be grounded and complete; this slice alone does not satisfy that goal.

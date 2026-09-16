# CDK root-owned evidence (LadybugDB acceptance and other runs the orchestrator makes)

Neo4j parity runs are in `neo4j-parity.md` beside this file. Each entry here names the line as run,
the revision, the exit code and the log.

- **CK5, the CD9 line at the recorded size** (`ai_docs/gates/rag-it-all/task-5-code-capture/GATES.md`
  CD9 CHECK, `HIPPO_TEST_STORE=ladybug HIPPO_CODE_ACCEPTANCE_FILES_PER_LANGUAGE=8`), run verbatim
  2026-09-16 by the orchestrator at `cb00f04` (S5b merged at `01a121e`), one LadybugDB acceptance
  process on the machine: exit 0, 354 passed, 2 skipped, log `/tmp/hippo-orch-cd9-n8.log`. The
  code path through the git and local connectors and the coordinator lane holds at the ledger's
  recorded size.

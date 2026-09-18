"""The Connector Developer Kit: the contract a connector implements and the kit's pure helpers.

`hippo.connectors` is a bounded context above `hippo.knowledge`: it imports `knowledge` (and
`ingest`, for the reader predicates), and nothing imports it back
(`tests/unit/test_connector_contract.py::test_knowledge_package_never_imports_connectors`).

This marker imports nothing, so `import hippo.connectors` costs nothing and `hippo --help` stays
cheap. Import the module you need:

    base.py         the descriptor, the emission records, the protocol, `token_count`
    keys.py         canonical keys and `KnowledgeObject` identities, from `key_template`
    classify.py     classification on connect: declaration, then content, then name
    render.py       labels, fact text and edge statements from registered templates
    emit.py         capture records, the policy record and the batch-to-records binder
    guard.py        the per-thread effects guard `emit` runs inside
    http.py         the bounded provider client, its six error classes, record and replay
    credentials.py  `env:` and `file:` credential references, and URL redaction
    loader.py       discovery: built-ins, enabled in-repo packages, allowlisted entry points
    sync.py         the sync runtime: lease, page, capture, checkpoint, emit, bind, stage, publish
"""

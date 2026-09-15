"""The Connector Developer Kit: the contract a connector implements and the kit's pure helpers.

`hippo.connectors` is a bounded context above `hippo.knowledge`: it imports `knowledge` (and
`ingest`, for the reader predicates), and nothing imports it back
(`tests/unit/test_connector_contract.py::test_knowledge_package_never_imports_connectors`).

This marker imports nothing, so `import hippo.connectors` costs nothing and `hippo --help` stays
cheap. Import the module you need:

    base.py      the descriptor, the emission records, the protocol, `token_count`
    keys.py      canonical keys and `KnowledgeObject` identities, generated from `key_template`
    classify.py  classification on connect: declaration, then content, then name
"""

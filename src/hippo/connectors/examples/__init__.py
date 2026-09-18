"""Example connectors shipped with hippo, discovered by the loader and enabled by an operator.

`loader.IN_REPO_PACKAGES` names this package, so every directory here that holds an `__init__.py`
and a `connector.py` is discovered by `hippo connector list` and by `GET /api/connectors`. Discovery
is not registration: an example's `TypeExtension` reaches the process registry only once an operator
has enabled its kind (design section 9, ruling R50), so adding one moves no production generation's
`registry_fingerprint`.
"""

"""The fixture connector: never shipped, never auto-registered (ruling R10).

types.py      the vocabulary a test registers with `extension_scope()`
provider.py   an in-memory provider behind `httpx.MockTransport`
connector.py  `FixtureConnector`, `FixtureConfig`, `DESCRIPTOR`
"""

from .connector import BASIC_CASE, DESCRIPTOR, FixtureConfig, FixtureConnector
from .provider import FixtureProvider
from .types import FIXTURE_EXTENSION, FixtureNoteAttributes

# The kit's `load_connector_package` resolves a package through the name design section 9 names,
# and the loader keeps the descriptor name, the connector kind and `Connector.kind` equal (R64).
Connector = FixtureConnector

__all__ = [
    "BASIC_CASE",
    "DESCRIPTOR",
    "FIXTURE_EXTENSION",
    "Connector",
    "FixtureConfig",
    "FixtureConnector",
    "FixtureNoteAttributes",
    "FixtureProvider",
]

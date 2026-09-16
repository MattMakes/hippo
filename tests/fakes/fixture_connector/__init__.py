"""The fixture connector: never shipped, never auto-registered (ruling R10).

types.py      the vocabulary a test registers with `extension_scope()`
provider.py   an in-memory provider behind `httpx.MockTransport`
connector.py  `FixtureConnector`, `FixtureConfig`, `DESCRIPTOR`
"""

from .connector import BASIC_CASE, DESCRIPTOR, FixtureConfig, FixtureConnector
from .provider import FixtureProvider
from .types import FIXTURE_EXTENSION, FixtureNoteAttributes

__all__ = [
    "BASIC_CASE",
    "DESCRIPTOR",
    "FIXTURE_EXTENSION",
    "FixtureConfig",
    "FixtureConnector",
    "FixtureNoteAttributes",
    "FixtureProvider",
]

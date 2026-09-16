"""The `incidents_ndjson` connector package.

`Connector` is the name the loader and `hippo connector validate` resolve (design section 9,
ruling R64). It must be the class whose `descriptor.name` equals this package's directory name
and the connector kind `types.py` registers: the loader refuses any disagreement.
"""

from .connector import IncidentsNdjsonConnector as Connector

__all__ = ["Connector"]

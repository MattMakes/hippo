"""The `local` connector: the saved bytes of a pasted text, an uploaded file or an archive.

`Connector` is the name the kit's package convention exports (`loader.PACKAGE_FILES`). `local` is a
built-in connector kind with no `Connector` row of its own (ruling R5), so `loader` keeps its
built-in entry rather than discovering this directory as an installable package; the export is here
so the package is well formed for the scaffold's own checks.

`managed_activation` imports `connector.py` directly, so this marker costs nothing it does not use.
"""

from .connector import LocalConnector, LocalSourceConfig

Connector = LocalConnector  # the name `loader._package_export` reads

__all__ = ["Connector", "LocalConnector", "LocalSourceConfig"]

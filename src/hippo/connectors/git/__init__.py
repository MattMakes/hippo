"""The `git` connector: one public repository, cloned into the managed build's own checkout.

`Connector` is the name the kit's package convention exports (`loader.PACKAGE_FILES`). `git` is a
built-in connector kind with no `Connector` row of its own (ruling R5), so `loader` keeps its
built-in entry rather than discovering this directory as an installable package (ruling R69); the
export is here so the package is well formed for the scaffold's own checks.

`managed_activation` imports `connector.py` directly, so this marker costs nothing it does not use.
"""

from .connector import GitConnector, GitSourceConfig

Connector = GitConnector  # the name `loader._package_export` reads

__all__ = ["Connector", "GitConnector", "GitSourceConfig"]

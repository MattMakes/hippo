"""The vocabulary the `local` connector registers: none.

Ruling R46 gives every descriptor a `TypeExtension`, and this one is empty on purpose. The prose
and code lanes write built-in object, artifact and locator kinds only (plan section 4.1), so the
connector asks for no registration and `descriptor.validate_against` can only ever refuse it if a
built-in were removed.
"""

from __future__ import annotations

from ..base import TypeExtension

EXTENSION = TypeExtension()

"""The fact templates the `incidents_ndjson` connector renders.

Each template becomes one rendered unit per object (design section 6). Every field in `text` must
be named in `consumes`, except `{key}`, which is the object's own key. Change `text` and the
version together: the registry lock pins `name@version`, and a template whose text changed under
the same version is a contract violation.
"""

from __future__ import annotations

from hippo.knowledge.registry import FactTemplate

SUMMARY = FactTemplate(
    name="summary",
    version="1",
    consumes=("title",),
    text="Record {key} is titled {title}",
)

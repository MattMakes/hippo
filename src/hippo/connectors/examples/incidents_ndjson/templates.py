"""The fact templates the `incidents_ndjson` connector renders.

Each template becomes one rendered unit per object (design section 6). Every field in `text` must
be named in `consumes`, except `{key}` and `{label}`, which are the object's own. Change `text` and
the version together: the registry lock pins `name@version`, and a template whose text changed under
the same version is a contract violation.

The two templates are deliberately asymmetric. A summary can be written about any incident the tool
reported at all; a resolution can only be written about one the tool has resolved. Because
`incident_resolution` consumes `resolved_at` and the three intervals, an incident missing any of
them renders one fact instead of two, and the omission is counted rather than guessed
(specification section 5.7: no MTTR when the tool has no resolved time).
"""

from __future__ import annotations

from hippo.connectors.base import FactTemplate

INCIDENT_SUMMARY = FactTemplate(
    name="incident_summary",
    version="1",
    consumes=("number", "severity", "title", "status", "service", "started_at"),
    text="INC-{number} ({severity}) {title}: {status}; affected {service} from {started_at}",
)
INCIDENT_RESOLUTION = FactTemplate(
    name="incident_resolution",
    version="1",
    consumes=("number", "mttd_minutes", "mttm_minutes", "mttr_minutes", "resolved_at"),
    text=(
        "INC-{number} was detected in {mttd_minutes} minutes, mitigated in {mttm_minutes} "
        "and resolved in {mttr_minutes}, at {resolved_at}"
    ),
)

"""The `incidents_ndjson` connector's own test: the whole kit, over every case under `fixtures/`.

`validate_package` opens a temporary store of its own, so this needs no running hippo, no
credentials and no network. `hippo connector validate .` runs the same checks from the shell.
"""

from pathlib import Path

from hippo.connectors.testing import validate_package

PACKAGE = Path(__file__).resolve().parents[1]


def test_the_incidents_ndjson_connector_passes_the_kit() -> None:
    report = validate_package(PACKAGE)
    assert report.passed, report.to_json()

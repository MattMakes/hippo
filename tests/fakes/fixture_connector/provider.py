"""An in-memory provider behind `httpx.MockTransport` (plan section 11).

Three routes, exactly the ones the fixture connector calls:

    GET api/partitions/{partition}/changes?page={n}&scan={changes|inventory}
    GET api/notes/{quoted external id}
    GET api/notes/{quoted external id}/acl

`scan=inventory` walks the whole partition in `page_size` chunks and marks its last page
`complete`, which is what `ConnectorCapabilities(inventory=True)` promises. That last page hands
back a *changes* cursor, so the run after a full walk reads the incremental feed instead of
walking again.

Everything a test needs to drive the failure matrix is a mutator here rather than a monkeypatch:
replace a note, delete one, hide one from the inventory only, change an ACL, fail a page with a
status, replay a page inside one run, and count requests.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, unquote

import httpx

DEFAULT_PARTITION = "notes"
DEFAULT_INSTANCE = "https://fixture.example"


class FixtureProvider:
    def __init__(
        self,
        *,
        instance: str = DEFAULT_INSTANCE,
        partition: str = DEFAULT_PARTITION,
        notes: dict | None = None,
        policies: dict | None = None,
        pages: list | None = None,
        page_size: int = 1,
    ) -> None:
        self.instance = instance
        self.partition = partition
        self.notes: dict[str, dict] = dict(notes or {})
        self.policies: dict[str, dict] = dict(policies or {})
        self.page_size = page_size
        self._case_pages = list(pages or [])
        self.feed: list[list[dict]] = []
        self.hidden: set[str] = set()
        self.requests: list[str] = []
        self.failures: dict[int, int] = {}
        self.repeat_first_page = False
        self._repeated = False

    # ------------------------------------------------------------------ construction

    @classmethod
    def from_case(cls, case_dir, *, instance: str = DEFAULT_INSTANCE, partition: str | None = None):
        """Load `config.json`, `changes.json`, `policies.json` and `inputs/` (design section 8)."""
        case = Path(case_dir)
        config = json.loads((case / "config.json").read_text(encoding="utf-8"))
        changes = json.loads((case / "changes.json").read_text(encoding="utf-8"))
        policies = json.loads((case / "policies.json").read_text(encoding="utf-8"))
        notes = {}
        for path in sorted((case / "inputs").iterdir()):
            note = json.loads(path.read_text(encoding="utf-8"))
            notes[unquote(path.name)] = note
        chosen = partition or config.get("partition", DEFAULT_PARTITION)
        provider = cls(
            instance=instance,
            partition=chosen,
            notes=notes,
            policies=policies,
            pages=changes.get("pages", []),
        )
        for note in provider.notes.values():
            note["url"] = f"{instance}/notes/{note['id']}"
        return provider

    def case_pages(self) -> list[list[dict]]:
        """The `changes.json` pages as loaded, for a test that asserts the case's shape."""
        return [list(page) for page in self._case_pages]

    # ------------------------------------------------------------------ mutators

    def put_note(self, note: dict) -> None:
        note = dict(note)
        note.setdefault("url", f"{self.instance}/notes/{note['id']}")
        self.notes[note["id"]] = note
        self.hidden.discard(note["id"])
        self.push_changes([{"operation": "upsert", "external_id": note["id"]}])

    def hide_note(self, external_id: str) -> None:
        """Gone from the provider without a deletion event: only a complete scan finds it."""
        self.hidden.add(external_id)

    def delete_note(self, external_id: str) -> None:
        self.hide_note(external_id)
        self.push_changes([{"operation": "delete", "external_id": external_id}])

    def set_policy(self, external_id: str, observation: dict) -> None:
        self.policies[external_id] = dict(observation)

    def push_changes(self, changes: list[dict]) -> None:
        self.feed.append([dict(change) for change in changes])

    def fail_page(self, index: int, status: int) -> None:
        self.failures[index] = status

    def clear_failures(self) -> None:
        self.failures.clear()
        self._repeated = False

    # ------------------------------------------------------------------ the transport

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.lstrip("/")
        self.requests.append(request.url.path)
        query = parse_qs(request.url.query.decode("ascii"))
        segments = path.split("/")
        if segments[:2] == ["api", "partitions"] and segments[-1] == "changes":
            return self._changes(unquote(segments[2]), query)
        if segments[:2] == ["api", "notes"] and len(segments) == 3:
            return self._note(unquote(segments[2]))
        if segments[:2] == ["api", "notes"] and segments[3:] == ["acl"]:
            return self._acl(unquote(segments[2]))
        return httpx.Response(404, json={"error": "no such route"})

    def _visible(self) -> list[str]:
        return sorted(name for name in self.notes if name not in self.hidden)

    def _changes(self, partition: str, query) -> httpx.Response:
        if partition != self.partition:
            return httpx.Response(404, json={"error": "no such partition"})
        page = int(query.get("page", ["0"])[0])
        scan = query.get("scan", ["changes"])[0]
        status = self.failures.get(page)
        if status is not None:
            return httpx.Response(status, json={"error": "page unavailable"})
        if scan == "inventory":
            return httpx.Response(200, json=self._inventory_page(page))
        return httpx.Response(200, json=self._feed_page(page))

    def _inventory_page(self, page: int) -> dict:
        names = self._visible()
        size = max(1, self.page_size)
        chunk = names[page * size : (page + 1) * size]
        last = (page + 1) * size >= len(names)
        if self.repeat_first_page and page == 0 and not self._repeated:
            self._repeated = True
            return self._page(chunk, "upsert", next_page=0, scan="inventory", complete=False)
        if last:
            # The walk is finished: hand back a *changes* cursor, so the next run reads the feed.
            return self._page(chunk, "upsert", next_page=0, scan="changes", complete=True)
        return self._page(chunk, "upsert", next_page=page + 1, scan="inventory", complete=False)

    def _feed_page(self, page: int) -> dict:
        if page >= len(self.feed):
            return {
                "partition": self.partition,
                "changes": [],
                "next_cursor": None,
                "complete": False,
                "warnings": [],
            }
        changes = [
            {
                "ref": {
                    "partition": self.partition,
                    "artifact_kind": "document",
                    "external_id": change["external_id"],
                },
                "operation": change["operation"],
            }
            for change in self.feed[page]
        ]
        more = page + 1 < len(self.feed)
        return {
            "partition": self.partition,
            "changes": changes,
            "next_cursor": self._cursor(page + 1, "changes") if more else None,
            "complete": False,
            "warnings": [],
        }

    def _page(self, names, operation, *, next_page, scan, complete) -> dict:
        return {
            "partition": self.partition,
            "changes": [
                {
                    "ref": {
                        "partition": self.partition,
                        "artifact_kind": "document",
                        "external_id": name,
                    },
                    "operation": operation,
                }
                for name in names
            ],
            "next_cursor": self._cursor(next_page, scan),
            "complete": complete,
            "warnings": [],
        }

    def _cursor(self, page: int, scan: str) -> dict:
        return {"partition": self.partition, "value": json.dumps({"page": page}), "scan": scan}

    def _note(self, external_id: str) -> httpx.Response:
        note = self.notes.get(external_id)
        if note is None or external_id in self.hidden:
            return httpx.Response(404, json={"error": "no such note"})
        return httpx.Response(
            200,
            content=json.dumps(note, sort_keys=True).encode("utf-8"),
            headers={"content-type": "application/json"},
        )

    def _acl(self, external_id: str) -> httpx.Response:
        if external_id not in self.notes or external_id in self.hidden:
            return httpx.Response(404, json={"error": "no such note"})
        return httpx.Response(200, json=self.policies.get(external_id, {"state": "unknown"}))

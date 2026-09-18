"""
A deterministic multi-hundred-file git repository for the managed code capture acceptance run.

Gate CD9 asks for a representative repository rather than the handful of files the slice suites
use: several hundred files across every walker language, the text files a repository always has,
and one of each thing capture must decline. `build_code_capture_repository` writes it at test time
(a nested `.git` cannot be checked in) with pinned identities and dates, so two builds in two
folders produce the same bytes and the same commit SHAs.

What the tree holds, for `files_per_language` = N:

* N files each of Python, TypeScript, Go, C# and Rust, each with a class or struct, methods and a
  free function that call one another, and the Python ones importing a shared module;
* N // 4 (at least two) SQL schemas and N // 4 YAML config files;
* `README.md` and `docs/architecture.md` (plain prose: captured, OpenIE deferred), and `NOTES`,
  `LICENSE`, `Makefile` and `go.mod` (extensionless or known-name text: captured, unparsed);
* one of each exclusion: `.git` and an untracked `web/node_modules/` (ignored paths), an untracked
  `data/huge.json` above `readers.MAX_FILE_BYTES` (too large), `data/blob.json` with NUL bytes
  (binary), `assets/logo.png` (no reader), and `fleet_link.py`, a committed symlink;
* one of each shape the CD10 review found the staged code writer refusing or dropping:
  `services/python/shapes/report.py` (a function longer than one chunk),
  `services/python/shapes/orders_cli.py` (a function that selects and updates the `orders` table
  `db/schema.sql` defines, and a module-level `main()` call under the main guard) and
  `csharp/Orders/Robot.cs` (two overloads of one method);
* four commits: the services, a Python edit, the later web clients, a Go edit. `refresh()` adds a
  fifth that edits one Python helper.

That is 5N + 2 * max(2, N // 4) + 10 accepted files: 274 at the default N = 48, 54 at N = 8 and
24 at N = 2.

The returned `CodeCaptureRepository` is the expectation a test asserts against, computed here
beside the bytes rather than hard-coded in the test.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from tests.conftest import git_env

IDENTITY = ("Hippo Fleet", "fleet@hippo.test")
OVERSIZED_BYTES = 2_100_000

PYTHON_SHARED = '''"""The total every order service starts from."""


def shared_total(order):
    return len(order)
'''

PYTHON = '''"""Order service {i}."""

from services.python.pkg0.mod000 import shared_total


class OrderService{i}:
    """Places and saves the orders of shard {i}."""

    def place(self, order):
        return shared_total(order) + {i}

    def save(self, order):
        return self.place(order)


def helper_{i}(value):
    return value * {i}
'''

TYPESCRIPT = """export class OrderClient{i} {
  constructor(readonly base: string) {}

  submit(order: string): string {
    return describe{i}(`${this.base}/${order}`);
  }
}

export function describe{i}(order: string): string {
  return order.toUpperCase();
}
"""

GO = """package orders

type Shard{i} struct {
	Name string
}

func (s *Shard{i}) Place(total int) int {
	return scale{i}(total)
}

func scale{i}(total int) int {
	return total * {i}
}
"""

CSHARP = """namespace Fleet.Orders;

public class Ledger{i}
{
    public int Place(int total)
    {
        return Scale(total);
    }

    private int Scale(int total)
    {
        return total * {i};
    }
}
"""

RUST = """pub struct Shard{i} {
    pub name: String,
}

impl Shard{i} {
    pub fn place(&self, total: u64) -> u64 {
        scale_{i}(total)
    }
}

fn scale_{i}(total: u64) -> u64 {
    total * {i}
}
"""

SQL = "CREATE TABLE orders_{i} (\n  id INT,\n  total INT\n);\n\nSELECT id, total FROM orders_{i};\n"
YAML = "name: service-{i}\nreplicas: {i}\n"

# The ordinary shapes the CD10 review found the staged code writer refusing or dropping (R21-B1,
# R21-B3). The unit suites build each one as a small tree; the repository below carries them all.

# A function longer than one chunk (`chunk_size_chars=1500`), so several passages observe it.
LONG_FUNCTION = (
    "def build_report():\n"
    + "".join(f"    value_{i} = {i} * 2 + 1  # padding text\n" for i in range(400))
    + "    return 1\n"
)

# Two C# overloads, which share one native symbol ID.
CSHARP_OVERLOADS = """\
namespace Acme
{
    public class Robot
    {
        public int Move(int steps) { return steps; }

        public int Move(string steps) { return 1; }
    }
}
"""

# A table defined in one file...
ORDERS_SCHEMA = "CREATE TABLE orders (id INT, total INT);\n"

# ...and a function in another directory that selects and updates it: READS and WRITES on one pair.
READ_WRITE = (
    "def touch(cursor):\n"
    '    cursor.execute("SELECT id FROM orders")\n'
    '    cursor.execute("UPDATE orders SET total = 1")\n'
    "    return cursor\n"
)

# A module-level call under the main guard: CONTAINS and INVOKES between the module and `main`.
MAIN_GUARD = 'def main():\n    return 1\n\n\nif __name__ == "__main__":\n    main()\n'

PROSE = {
    "README.md": "# Fleet\n\nThe fleet repository holds the order services in five languages.\n",
    "docs/architecture.md": "# Architecture\n\nEvery shard places orders and scales their totals.\n",
}
UNPARSED = {
    "NOTES": "Release notes, with no extension, so no reader names a grammar for it.\n",
    "LICENSE": "Permission is granted to use this fixture for tests.\n",
    "Makefile": "test:\n\tpytest\n",
    "go.mod": "module example.com/fleet\n\ngo 1.22\n",
}

SYMLINK = "fleet_link.py"
BINARY = "data/blob.json"
OVERSIZED = "data/huge.json"
NO_READER = "assets/logo.png"
NODE_MODULES = "web/node_modules"


@dataclass(frozen=True)
class CodeCaptureRepository:
    """The checkout on disk and what a managed capture of it must record."""

    root: Path
    files: dict[str, bytes]
    languages: dict[str, tuple[str, ...]]
    accepted: frozenset[str]
    excluded: dict[str, frozenset[str]]
    prose: frozenset[str]
    unparsed: frozenset[str]
    commits: tuple[str, ...]  # newest first
    changed: str | None = None

    @property
    def head(self) -> str:
        return self.commits[0]

    def refresh(self) -> CodeCaptureRepository:
        """Commit one edited Python helper; every other file is byte-identical."""
        path = self.languages["python"][1]
        text = self.files[path].decode().replace("return value * 1\n", "return value * 1 + 1\n")
        files = {**self.files, path: text.encode()}
        _write(self.root, {path: files[path]})
        sha = _commit(self.root, "Adjust one python helper", len(self.commits))
        return replace(self, files=files, commits=(sha, *self.commits), changed=path)


def _render(template: str, i: int) -> bytes:
    return template.replace("{i}", str(i)).encode()


def _write(root: Path, files: dict[str, bytes]) -> None:
    for path, data in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _git(root: Path, *args: str, env=None) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True, env=env or git_env()
    )
    return result.stdout.strip()


def _commit(root: Path, message: str, ordinal: int) -> str:
    name, email = IDENTITY
    date = f"2026-02-{ordinal + 1:02d}T10:00:00+00:00"
    env = git_env(
        GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_AUTHOR_DATE=date,
        GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email, GIT_COMMITTER_DATE=date,
    )  # fmt: skip
    _git(root, "add", "-A", env=env)
    _git(root, "commit", "-q", "-m", message, env=env)
    return _git(root, "rev-parse", "HEAD")


def build_code_capture_repository(parent: Path, *, files_per_language: int = 48) -> CodeCaptureRepository:
    """Write the repository under `parent` and return it with its expected capture."""
    if files_per_language < 2:
        raise ValueError("The fixture needs at least two files per language")
    n = files_per_language
    root = Path(parent)
    root.mkdir(parents=True, exist_ok=False)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, env=git_env())
    # Build output a developer never commits: the walk still meets it in the working tree.
    (root / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "info" / "exclude").write_text(f"/{NODE_MODULES}/\n/{OVERSIZED}\n")

    python = {f"services/python/pkg{i // 12}/mod{i:03d}.py": _render(PYTHON, i) for i in range(1, n)}
    python = {"services/python/pkg0/mod000.py": PYTHON_SHARED.encode(), **python}
    late = max(1, n // 4)
    typescript = {f"web/src/client{i:03d}.ts": _render(TYPESCRIPT, i) for i in range(n)}
    go = {f"go/orders/shard{i:03d}.go": _render(GO, i) for i in range(n)}
    csharp = {f"csharp/Orders/Ledger{i:03d}.cs": _render(CSHARP, i) for i in range(n)}
    rust = {f"rust/src/shard{i:03d}.rs": _render(RUST, i) for i in range(n)}
    sql = {f"db/schema{i:02d}.sql": _render(SQL, i) for i in range(max(2, n // 4))}
    config = {f"config/service{i:02d}.yaml": _render(YAML, i) for i in range(max(2, n // 4))}
    prose = {path: text.encode() for path, text in PROSE.items()}
    unparsed = {path: text.encode() for path, text in UNPARSED.items()}
    # The review shapes, once each. The Python ones sort after every `services/python/pkg*` module,
    # so `refresh()` and the edited-shard commit below still pick the files they always picked.
    shapes = {
        "services/python/shapes/report.py": LONG_FUNCTION.encode(),
        "services/python/shapes/orders_cli.py": f"{READ_WRITE}\n\n{MAIN_GUARD}".encode(),
    }
    overloads = {"csharp/Orders/Robot.cs": CSHARP_OVERLOADS.encode()}
    schema = {"db/schema.sql": ORDERS_SCHEMA.encode()}
    declined = {
        BINARY: b"\x00\x01\x02\x00binary\x00",
        NO_READER: b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR",
        f"{NODE_MODULES}/left-pad/index.js": b"module.exports = (s) => s;\n",
        OVERSIZED: b'{"padding": "' + b"x" * OVERSIZED_BYTES + b'"}\n',
    }

    later_clients = dict(list(typescript.items())[-late:])
    first = {
        **python,
        **{path: data for path, data in typescript.items() if path not in later_clients},
        **go,
        **csharp,
        **rust,
        **sql,
        **config,
        **prose,
        **unparsed,
        **declined,
        **shapes,
        **overloads,
        **schema,
    }
    _write(root, first)
    os.symlink("services/python/pkg0/mod000.py", root / SYMLINK)
    commits = [_commit(root, "Add the fleet services", 0)]

    edited = dict(list(python.items())[1:6])
    edited = {path: data.replace(b"+ ", b"* 2 + ", 1) for path, data in edited.items()}
    _write(root, edited)
    commits.append(_commit(root, "Double the python shard totals", 1))

    _write(root, later_clients)
    commits.append(_commit(root, "Add the web clients", 2))

    tuned = {
        path: data.replace(b"return total * ", b"return 1 + total * ", 1)
        for path, data in list(go.items())[:3]
    }
    _write(root, tuned)
    commits.append(_commit(root, "Tune the go scaling", 3))

    files = {**first, **later_clients, **edited, **tuned}
    languages = {
        "python": tuple(sorted({**python, **shapes})),
        "typescript": tuple(sorted(typescript)),
        "go": tuple(sorted(go)),
        "csharp": tuple(sorted({**csharp, **overloads})),
        "rust": tuple(sorted(rust)),
        "sql": tuple(sorted({**sql, **schema})),
    }
    accepted = frozenset(files) - {BINARY, NO_READER, OVERSIZED, f"{NODE_MODULES}/left-pad/index.js"}
    return CodeCaptureRepository(
        root=root,
        files=files,
        languages=languages,
        accepted=accepted,
        excluded={
            "ignored_path": frozenset({".git", NODE_MODULES}),
            "too_large": frozenset({OVERSIZED}),
            "binary": frozenset({BINARY}),
            "unsupported_language": frozenset({NO_READER}),
            "symlink": frozenset({SYMLINK}),
        },
        prose=frozenset(prose),
        unparsed=frozenset(unparsed),
        commits=tuple(reversed(commits)),
    )

#!/usr/bin/env python
"""Probe a NEW disposable Ladybug database; never open Hippo's configured store.

Exit 0: core probe and cleanup pass; optional native failures/unavailability select
the explicit fallback. Exit 1: core, cleanup, or report-writing failure. Exit 2:
invalid CLI arguments. Native promotion is always disabled: these small fixtures
do not prove application ACLs, concurrent revocation, or BM25 isolation.

No INSTALL, UPDATE, model calls, extension downloads, or application imports.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

NATIVE_CHECKS = (
    "create",
    "query",
    "dimensions",
    "insert",
    "edit",
    "delete",
    "rebuild",
    "transaction",
    "transaction_create_index",
    "reopen_load",
    "reopen_query",
)
GUARANTEES = (
    "application_acl",
    "generation_membership",
    "bitemporal_membership",
    "concurrent_revocation",
    "native_filtered_top_k",
    "native_score_noninterference",
    "bm25_correctness",
    "target_slice_recall",
    "crash_recovery",
)
EDITED_VECTORS = {"a": [-1.0, 0.0, 0.0], "b": [0.8, 0.6, 0.0], "c": [0.95, 0.05, 0.0]}


def rows(connection, statement, parameters=None):
    """Materialize and close one result; all statements are internal constants."""
    result = connection.execute(statement, parameters or {})
    try:
        output = []
        while result.has_next():
            output.append(result.get_next())
        return output
    finally:
        result.close()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked(action):
    try:
        details = action()
        # Reject native NaN/Infinity before recording a successful check.
        json.dumps(details, allow_nan=False)
        return {"status": "passed", "details": details}
    except Exception as exc:
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def extension_unavailable(exc):
    """Only a definite missing installation is an expected capability absence."""
    return "official extension and has not been installed" in str(exc).lower()


def load_extension(connection, name):
    try:
        rows(connection, f"LOAD {name}")  # name is one of our two constants
        return {"status": "passed"}
    except Exception as exc:
        return {
            "status": "unavailable" if extension_unavailable(exc) else "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }


def rank_exact(candidates, query):
    """Fixture cosine oracle: finite nonzero 3D vectors, stable ID tie breaking."""
    q = np.asarray(query, dtype=np.float64)
    require(q.shape == (3,) and np.isfinite(q).all() and np.linalg.norm(q) > 0, "Invalid query vector")
    scored = []
    for identity, values in candidates:
        vector = np.asarray(values, dtype=np.float64)
        require(
            vector.shape == q.shape and np.isfinite(vector).all() and np.linalg.norm(vector) > 0,
            "Invalid fixture vector",
        )
        score = float(np.dot(vector, q) / (np.linalg.norm(vector) * np.linalg.norm(q)))
        require(np.isfinite(score), "Nonfinite cosine result")
        scored.append((identity, score))
    return sorted(scored, key=lambda row: (-row[1], row[0]))


def probe_exact(connection):
    """Test scoped extraction and exact ranking, not the application's ACL model."""
    rows(
        connection,
        "CREATE NODE TABLE ExactProbe(id STRING PRIMARY KEY, text STRING, embedding FLOAT[3], visible BOOL, generation STRING, valid_from INT64, valid_to INT64)",
    )
    fixtures = (
        ("allowed_a", [1.0, 0.0, 0.0], True, "g1", 100),
        ("allowed_b", [0.8, 0.6, 0.0], True, "g1", 100),
        ("hidden", [1.0, 0.0, 0.0], False, "g1", 100),
        ("staging", [1.0, 0.0, 0.0], True, "g2", 100),
        ("expired", [1.0, 0.0, 0.0], True, "g1", 49),
    )
    for identity, vector, visible, generation, upper in fixtures:
        rows(
            connection,
            "CREATE (:ExactProbe {id:$id,text:decode($text),embedding:$vector,visible:$visible,generation:$generation,valid_from:0,valid_to:$upper})",
            {
                "id": identity,
                "text": b'{"invoice":"ledger"}',
                "vector": vector,
                "visible": visible,
                "generation": generation,
                "upper": upper,
            },
        )

    def ranking():
        selected = rows(
            connection,
            "MATCH (p:ExactProbe) WHERE p.visible = $visible AND p.generation = $generation AND p.valid_from <= $at AND p.valid_to > $at RETURN p.id,p.embedding",
            {"visible": True, "generation": "g1", "at": 50},
        )
        return rank_exact(selected, [1.0, 0.0, 0.0])

    initial = ranking()
    require([row[0] for row in initial] == ["allowed_a", "allowed_b"], "Wrong eligible ranking")
    rows(
        connection,
        "MATCH (p:ExactProbe {id:'hidden'}) SET p.text='changed hidden terms',p.embedding=[-1.0,0.0,0.0]",
    )
    require(ranking() == initial, "Hidden fixture change influenced exact ranking")
    rows(connection, "MATCH (p:ExactProbe {id:'allowed_a'}) SET p.valid_to=49")
    retired = ranking()
    require([row[0] for row in retired] == ["allowed_b"], "Retired record remains eligible")
    rows(connection, "MATCH (p:ExactProbe {id:'allowed_b'}) DELETE p")
    require(ranking() == [], "Deleted record remains eligible")
    try:
        rows(connection, "CREATE (:ExactProbe {id:'bad_dimension',embedding:[1.0,0.0]})")
    except RuntimeError as exc:
        require("Expected: 3, Actual: 2" in str(exc), "Unexpected dimension rejection")
    else:
        raise ValueError("Wrong vector dimension accepted")
    return {
        "initial_ids": [row[0] for row in initial],
        "scores": [row[1] for row in initial],
        "after_retirement_ids": [row[0] for row in retired],
        "after_delete_ids": [],
        "hidden_edit_unchanged": True,
        "fixed_dimension_rejection": True,
        "boundary": "Scalar fixture filters only; not application ACL, concurrent revocation, or BM25 proof.",
    }


def native_statements(name):
    table = "FtsProbe" if name == "fts" else "VectorProbe"
    index = "probe_index"
    if name == "fts":
        create = f"CALL CREATE_FTS_INDEX('{table}','{index}',['text'],stemmer := 'none')"
        search = f"CALL QUERY_FTS_INDEX('{table}','{index}','ledger',top := 10) RETURN node.id,score ORDER BY score DESC,node.id"
        drop = f"CALL DROP_FTS_INDEX('{table}','{index}')"
    else:
        create = f"CALL CREATE_VECTOR_INDEX('{table}','{index}','embedding',metric := 'cosine')"
        search = f"CALL QUERY_VECTOR_INDEX('{table}','{index}',[1.0,0.0,0.0],10) RETURN node.id,distance ORDER BY distance,node.id"
        drop = f"CALL DROP_VECTOR_INDEX('{table}','{index}')"
    return table, create, search, drop


def native_results(connection, name, expected, *, vectors=None):
    result = rows(connection, native_statements(name)[2])
    identities = [row[0] for row in result]
    require(
        len(identities) == len(expected) and set(identities) == set(expected),
        f"Unexpected {name} result membership: {identities}",
    )
    require(all(np.isfinite(row[1]) for row in result), "Nonfinite native score")
    if name == "vector":
        vectors = vectors or {**EDITED_VECTORS, "a": [1.0, 0.0, 0.0]}
        oracle = dict(rank_exact([(identity, vectors[identity]) for identity in expected], [1.0, 0.0, 0.0]))
        require(
            all(abs(distance - (1.0 - oracle[identity])) < 1e-5 for identity, distance in result),
            "Native cosine distance disagrees with current fixture vectors",
        )
    return result


def native_current_results(connection, name):
    """Compare the index with source rows, including partially completed writes."""
    table = native_statements(name)[0]
    source = rows(connection, f"MATCH (p:{table}) RETURN p.id,p.text,p.embedding")
    expected = [
        identity for identity, text, _vector in source if name == "vector" or "ledger" in text.split()
    ]
    return native_results(
        connection, name, expected, vectors={identity: vector for identity, _text, vector in source}
    )


def rollback_if_active(connection):
    """An engine autoabort is harmless; other rollback failures remain failures."""
    try:
        rows(connection, "ROLLBACK")
        return {"already_aborted": False}
    except RuntimeError as exc:
        if "no active transaction" not in str(exc).lower():
            raise
        return {"already_aborted": True}


def probe_index_transaction(connection, create):
    rows(connection, "BEGIN TRANSACTION")
    try:
        try:
            rows(connection, create.replace("probe_index", "transaction_index"))
            outcome = {"supported": True}
        except RuntimeError as exc:
            # Only known explicit-transaction restrictions describe absence of
            # support. Storage corruption and every unfamiliar error must fail.
            restriction = str(exc).lower()
            if not any(
                message in restriction
                for message in (
                    "index creation cannot run in an explicit transaction",
                    "cannot execute this statement within an active transaction",
                    "cannot execute this statement in an active transaction",
                )
            ):
                raise
            outcome = {"supported": False, "error": str(exc)}
    finally:
        rollback = rollback_if_active(connection)
    indexes = rows(connection, "CALL SHOW_INDEXES() RETURN *")
    require(not any("transaction_index" in str(row) for row in indexes), "Rolled-back index remains")
    return {**outcome, "rollback": rollback}


def probe_native(connection, name):
    """Run lifecycle operations only when an already installed extension loads."""
    output = {
        "load": load_extension(connection, name),
        "extension_version": None,
        "extension_version_note": "Loaded catalog reports source/path, not a separate semantic version; no version inferred",
        "checks": {
            key: {"status": "not_run", "reason": "Prerequisite unavailable or failed"}
            for key in NATIVE_CHECKS
        },
    }
    if output["load"]["status"] != "passed":
        return output
    table, create, _search, drop = native_statements(name)

    def create_index():
        rows(connection, f"CREATE NODE TABLE {table}(id STRING PRIMARY KEY,text STRING,embedding FLOAT[3])")
        rows(connection, f"CREATE (:{table} {{id:'a',text:'invoice ledger',embedding:[1.0,0.0,0.0]}})")
        rows(connection, f"CREATE (:{table} {{id:'b',text:'ocean ledger',embedding:[0.8,0.6,0.0]}})")
        rows(connection, create)
        return {"create_statement": create}

    def dimension():
        try:
            rows(connection, f"CALL QUERY_VECTOR_INDEX('{table}','probe_index',[1.0,0.0],10) RETURN node.id")
        except RuntimeError as exc:
            require(
                any(word in str(exc).lower() for word in ("dimension", "size", "expected", "length")),
                "Unexpected failure while checking query dimension",
            )
            return {"rejected": True, "error": str(exc)}
        raise ValueError("Wrong query dimension accepted")

    def check_row(identity, expected):
        found = rows(connection, f"MATCH (p:{table}) WHERE p.id='{identity}' RETURN p.text,p.embedding")
        if expected is None:
            require(not found, f"Delete postcondition failed: {identity} remains")
            return
        require(len(found) == 1, f"Mutation postcondition failed: {identity} missing or duplicated")
        text, vector = expected
        require(
            found[0][0] == text and np.allclose(found[0][1], vector, rtol=0, atol=1e-6),
            f"Mutation postcondition failed: {identity} text/vector unchanged or incorrect",
        )

    def source_snapshot():
        return rows(connection, f"MATCH (p:{table}) RETURN p.id,p.text,p.embedding ORDER BY p.id")

    def mutate(statement, identity, expected):
        rows(connection, statement)
        check_row(identity, expected)
        return native_current_results(connection, name)

    def rebuild():
        rows(connection, drop)
        rows(connection, create)
        return native_current_results(connection, name)

    def transaction():
        before = rows(connection, native_statements(name)[2])
        source_before = source_snapshot()
        rows(connection, "BEGIN TRANSACTION")
        try:
            rows(connection, f"MATCH (p:{table} {{id:'b'}}) SET p.text='forest',p.embedding=[0.0,0.0,1.0]")
            check_row("b", ("forest", [0.0, 0.0, 1.0]))
        finally:
            rollback_if_active(connection)
        require(source_snapshot() == source_before, "Rollback postcondition failed: source rows changed")
        after = rows(connection, native_statements(name)[2])
        require(before == after, "Rolled-back edit altered index results")
        return {"rollback_preserves_results": True, "rollback_preserves_source_rows": True}

    actions = [
        ("create", create_index),
        ("query", lambda: native_results(connection, name, ["a", "b"])),
        (
            "insert",
            lambda: mutate(
                f"CREATE (:{table} {{id:'c',text:'ledger ledger',embedding:[0.95,0.05,0.0]}})",
                "c",
                ("ledger ledger", EDITED_VECTORS["c"]),
            ),
        ),
        (
            "edit",
            lambda: mutate(
                f"MATCH (p:{table} {{id:'a'}}) SET p.text='forest',p.embedding=[-1.0,0.0,0.0]",
                "a",
                ("forest", EDITED_VECTORS["a"]),
            ),
        ),
        (
            "delete",
            lambda: mutate(f"MATCH (p:{table} {{id:'c'}}) DELETE p", "c", None),
        ),
        ("rebuild", rebuild),
        ("transaction", transaction),
        ("transaction_create_index", lambda: probe_index_transaction(connection, create)),
    ]
    for key, action in actions:
        if key == "delete" and not rows(connection, f"MATCH (p:{table}) WHERE p.id='c' RETURN p.id"):
            output["checks"][key] = {
                "status": "not_run",
                "reason": "Insert did not create the deletion fixture",
            }
            continue
        output["checks"][key] = checked(action)
        if key == "create" and output["checks"][key]["status"] != "passed":
            break
        if key == "query" and name == "vector":
            output["checks"]["dimensions"] = checked(dimension)
    if name == "fts":
        output["checks"]["dimensions"] = {"status": "not_run", "reason": "Not applicable to lexical index"}
    return output


def cleanup_directory(path):
    shutil.rmtree(path)
    require(not path.exists(), "Temporary database directory still exists")


def probe():
    report = {
        "schema_version": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "exit_code": 1,
        "engine": {},
        "native": {},
        "guarantees": dict.fromkeys(GUARANTEES, "not_run"),
        "extension_install_attempted": False,
        "selection": {
            "native_enabled": False,
            "lexical": "authorized_view_bm25",
            "dense": "authorized_view_numpy_exact",
            "reasons": ["Application isolation/lifecycle/recall guarantees remain unproved"],
        },
    }
    directory = Path(tempfile.mkdtemp(prefix="hippo-store-capabilities-", dir="/tmp"))
    report["database_path"] = str(directory / "probe.lbug")
    database = connection = None
    try:
        import real_ladybug as lb

        report["engine"] = {
            "distribution": importlib.metadata.version("real_ladybug"),
            "version": lb.Database.get_version(),
            "storage_version": lb.Database.get_storage_version(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        }
        database = lb.Database(report["database_path"], buffer_pool_size=64 * 1024 * 1024, max_num_threads=1)
        connection = lb.Connection(database)
        report["official_extensions"] = checked(
            lambda: rows(connection, "CALL SHOW_OFFICIAL_EXTENSIONS() RETURN *")
        )
        report["loaded_extensions_initial"] = checked(
            lambda: rows(connection, "CALL SHOW_LOADED_EXTENSIONS() RETURN *")
        )
        exact = checked(lambda: probe_exact(connection))
        report["exact_baseline"] = {
            "status": exact["status"],
            **exact.get("details", {}),
            **({"error": exact["error"]} if "error" in exact else {}),
        }
        for name in ("fts", "vector"):
            report["native"][name] = probe_native(connection, name)
        report["loaded_extensions"] = checked(
            lambda: rows(connection, "CALL SHOW_LOADED_EXTENSIONS() RETURN *")
        )
        connection.close()
        connection = None
        database.close()
        database = None
        database = lb.Database(report["database_path"], buffer_pool_size=64 * 1024 * 1024, max_num_threads=1)
        connection = lb.Connection(database)

        def reopen_core():
            count = rows(connection, "MATCH (p:ExactProbe) RETURN count(p)")
            require(count == [[4]], "Core fixture row count changed on reopen")
            return count

        report["core_reopen"] = checked(reopen_core)
        for name, native in report["native"].items():
            if native["load"]["status"] != "passed" or native["checks"]["create"]["status"] != "passed":
                continue
            native["checks"]["reopen_load"] = load_extension(connection, name)
            if native["checks"]["reopen_load"]["status"] == "passed":
                native["checks"]["reopen_query"] = checked(
                    lambda name=name: native_current_results(connection, name)
                )
        report["exit_code"] = 0 if exact["status"] == report["core_reopen"]["status"] == "passed" else 1
    except Exception as exc:
        report["core_error"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        for label, resource in (("connection_close", connection), ("database_close", database)):
            if resource is not None:
                report[label] = checked(resource.close)
                if report[label]["status"] == "failed":
                    report["exit_code"] = 1
        report["cleanup"] = checked(lambda: cleanup_directory(directory))
        if report["cleanup"]["status"] != "passed":
            report["exit_code"] = 1
    for name, native in report["native"].items():
        statuses = {native["load"]["status"], *(item["status"] for item in native["checks"].values())}
        if "unavailable" in statuses or "failed" in statuses:
            report["selection"]["reasons"].append(
                f"{name}: native capability unavailable or failed; see checks"
            )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="JSON report path; no database path is accepted"
    )
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != ".json" or args.output.is_symlink():
        parser.error("Output must be a .json report, not a database or symlink")
    temporary = None
    try:
        report = probe()
        serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=args.output.parent, prefix=".capabilities-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
        os.replace(temporary, args.output)
        print(f"Capability report written; native search disabled; exit {report['exit_code']}.")
        return report["exit_code"]
    except (OSError, ValueError, TypeError) as exc:
        print(f"Capability report failed: {type(exc).__name__}.")
        return 1
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    raise SystemExit(main())

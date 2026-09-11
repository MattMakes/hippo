#!/usr/bin/env python3
"""Repository evaluation command; fake profiles are diagnostics, never quality claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hippo.config import Config  # noqa: E402
from hippo.context import AppContext  # noqa: E402
from hippo.evals.rag_all import evaluate, load_fixture  # noqa: E402
from hippo.ollama import Ollama  # noqa: E402


@contextmanager
def fake_context(directory: Path):
    """Explicit repository-only doubles; the packaged evaluator accepts any context.

    Stable source identities keep code IDs and score tie-breaking reproducible.
    This deliberately does not load application environment or any existing store.
    """
    sys.path.insert(0, str(ROOT))
    from tests.fakes.fake_ollama import FakeOllama
    from tests.fakes.fake_store import FakeStore

    class EvaluationStore(FakeStore):
        def create_source(self, kind, name, meta, **kwargs):
            generated = super().create_source(kind, name, meta, **kwargs)
            ident = "eval-source-" + hashlib.sha256(name.encode()).hexdigest()
            row = self.sources.pop(generated)
            row["id"] = ident
            self.sources[ident] = row
            return ident

    fake = FakeOllama()
    client = fake.client()
    config = Config(data_dir=directory, openie_workers=1)
    ctx = AppContext(
        config,
        EvaluationStore(),
        Ollama("http://fake-ollama", config.llm_model, config.embed_model, client=client),
    )
    try:
        yield ctx
    finally:
        ctx.close()
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["legacy", "bm25", "dense", "hybrid", "all"], default="legacy")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--split", choices=["dev", "holdout"], default="dev")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check-targets", action="store_true")
    args = parser.parse_args(argv)
    if args.mode != "legacy":
        parser.error(f"mode not implemented: {args.mode}")
    if not args.retrieval_only:
        parser.error("answer evaluation not implemented; use --retrieval-only")
    if args.check_targets:
        parser.error("approved release targets are not available; baseline capture does not approve targets")
    try:
        fixture = load_fixture(args.fixture)
        with tempfile.TemporaryDirectory(prefix="hippo-rag-eval-") as directory:
            with fake_context(Path(directory)) as ctx:
                report = evaluate(fixture, ctx, split=args.split, model_profile="fake-hash128-v1")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        f"Saved {report['evaluated_count']}/{report['question_count']} evaluated questions to {args.output}; coverage gaps recorded. Fake-model harness diagnostics only."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

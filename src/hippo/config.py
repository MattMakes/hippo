"""
Settings for hippo, read from environment variables.

Every knob the app needs lives here, in one place, with a plain-English
description. Values come from the environment (docker-compose sets them),
and every one has a sensible default so `hippo` also runs straight from a
laptop with nothing but Ollama installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]")


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def parse_allowed_hosts(text: str) -> tuple[str, ...]:
    """
    Turn HIPPO_ALLOWED_HOSTS ("mybox, 192.168.1.5") into the full list: the local defaults
    plus what the user added. Ports are never part of an entry; "*" means "any host".
    """
    extra = [item.strip() for item in text.split(",") if item.strip()]
    hosts = list(DEFAULT_ALLOWED_HOSTS)
    for host in extra:
        if host not in hosts:
            hosts.append(host)
    return tuple(hosts)


@dataclass(frozen=True)
class Config:
    # Where the graph lives. "ladybug" (the default) is an embedded LadybugDB file under data_dir:
    # nothing to install or run. "neo4j" talks to a Neo4j server at neo4j_uri instead.
    store_backend: str = "ladybug"
    db_path: Path | None = None  # the .lbug file; None means <data_dir>/hippo.lbug
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "hippo-password"

    # Where the language model lives.
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "qwen3:8b"  # extracts facts, filters facts, answers, judges
    embed_model: str = "nomic-embed-text"  # turns text into vectors
    num_ctx: int = 8192  # context window we ask Ollama for (qwen3 defaults to 4k, too small)
    llm_timeout_seconds: float = 600.0  # local 8B models on CPU can be slow; be patient

    # Where uploaded files and cloned repos are kept.
    data_dir: Path = Path("./data")

    # Indexing behaviour.
    openie_workers: int = 2  # parallel LLM calls while extracting facts (Ollama serves ~1-4 at a time)
    chunk_size_chars: int = 1500  # ~350 tokens: small enough that 5 passages fit in the QA prompt
    chunk_overlap_chars: int = 150

    # Size limits (a memory is not a file server; huge inputs mostly cost hours of LLM time).
    max_upload_bytes: int = 50_000_000  # biggest upload or pasted text; bigger ones are refused
    max_text_chars: int = (
        20_000_000  # most text one source may turn into; past it the source fails as too large
    )

    # Web server.
    host: str = "127.0.0.1"  # this machine only; hippo is open until users exist. docker-compose sets 0.0.0.0 inside the container.
    port: int = 8000
    # Host names the web app answers to. Browsers send the address they used in the
    # Host header; anything else is refused so a page on attacker.example cannot point its
    # own DNS name at this machine and read the memory (a "DNS rebinding" attack).
    # HIPPO_ALLOWED_HOSTS adds names or IPs (comma-separated); "*" turns the check off.
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS

    @property
    def database_path(self) -> Path:
        """Where the embedded database file is (only meaningful when store_backend is "ladybug")."""
        return self.db_path if self.db_path is not None else self.data_dir / "hippo.lbug"

    @property
    def store_location(self) -> str:
        """A one-line description of where the graph lives, for the Settings page and the CLI."""
        return self.neo4j_uri if self.store_backend == "neo4j" else str(self.database_path)


STORE_BACKENDS = ("ladybug", "neo4j")


def parse_store_backend(text: str) -> str:
    value = text.strip().lower()
    if value not in STORE_BACKENDS:
        raise ValueError(f"HIPPO_STORE must be one of {', '.join(STORE_BACKENDS)}, not {text!r}")
    return value


def load_config() -> Config:
    """Build a Config from environment variables (falling back to the defaults above)."""
    db_path = _env("HIPPO_DB_PATH", "")
    return Config(
        store_backend=parse_store_backend(_env("HIPPO_STORE", Config.store_backend)),
        db_path=Path(db_path) if db_path else None,
        neo4j_uri=_env("NEO4J_URI", Config.neo4j_uri),
        neo4j_user=_env("NEO4J_USER", Config.neo4j_user),
        neo4j_password=_env("NEO4J_PASSWORD", Config.neo4j_password),
        ollama_url=_env("OLLAMA_URL", Config.ollama_url).rstrip("/"),
        llm_model=_env("HIPPO_LLM_MODEL", Config.llm_model),
        embed_model=_env("HIPPO_EMBED_MODEL", Config.embed_model),
        num_ctx=int(_env("HIPPO_NUM_CTX", str(Config.num_ctx))),
        llm_timeout_seconds=float(_env("HIPPO_LLM_TIMEOUT", str(Config.llm_timeout_seconds))),
        data_dir=Path(_env("HIPPO_DATA_DIR", str(Config.data_dir))),
        openie_workers=int(_env("HIPPO_OPENIE_WORKERS", str(Config.openie_workers))),
        chunk_size_chars=int(_env("HIPPO_CHUNK_SIZE", str(Config.chunk_size_chars))),
        chunk_overlap_chars=int(_env("HIPPO_CHUNK_OVERLAP", str(Config.chunk_overlap_chars))),
        max_upload_bytes=int(_env("HIPPO_MAX_UPLOAD_BYTES", str(Config.max_upload_bytes))),
        max_text_chars=int(_env("HIPPO_MAX_TEXT_CHARS", str(Config.max_text_chars))),
        host=_env("HIPPO_HOST", Config.host),
        port=int(_env("HIPPO_PORT", str(Config.port))),
        allowed_hosts=parse_allowed_hosts(_env("HIPPO_ALLOWED_HOSTS", "")),
    )

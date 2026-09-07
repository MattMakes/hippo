"""
Sanity checks for the files that ship hippo: docker-compose.yml, the Dockerfile,
the ./hippo launcher, .env.example and the CI workflow.

We cannot run Docker in the test environment, so these tests only check that
the files parse and say what they are supposed to say. They catch the kind of
typo that would otherwise only show up when someone tries `./hippo up`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
COMPOSE = ROOT / "docker-compose.yml"
DOCKERFILE = ROOT / "Dockerfile"
LAUNCHER = ROOT / "hippo"
ENV_EXAMPLE = ROOT / ".env.example"
CI = ROOT / ".github" / "workflows" / "ci.yml"
CONFIG = ROOT / "src" / "hippo" / "config.py"


# ------------------------------------------------------------- compose


def test_compose_parses_and_every_service_runs_something():
    compose = yaml.safe_load(COMPOSE.read_text())
    services = compose["services"]
    assert set(services) == {"neo4j", "app", "ollama"}
    for name, service in services.items():
        assert "image" in service or "build" in service, f"service {name} has neither image nor build"


def test_compose_app_keeps_its_graph_in_the_data_folder_by_default():
    """Plain `docker compose up` must need nothing but the app: the graph is an embedded file under ./data."""
    compose = yaml.safe_load(COMPOSE.read_text())
    app = compose["services"]["app"]
    env = app["environment"]
    assert env["HIPPO_STORE"] == "${HIPPO_STORE:-ladybug}"
    assert env["HIPPO_DATA_DIR"] == "/app/data"
    assert "./data:/app/data" in app["volumes"]  # the .lbug file lives there, so it survives rebuilds
    assert "depends_on" not in app, "the app must start without Neo4j (it copes with it coming up late)"
    assert "profiles" not in app
    assert "OLLAMA_URL" in env
    assert any("host.docker.internal" in h for h in app["extra_hosts"])


def test_compose_neo4j_is_an_opt_in_profile_wired_to_the_app():
    compose = yaml.safe_load(COMPOSE.read_text())
    neo4j = compose["services"]["neo4j"]
    assert neo4j["profiles"] == ["neo4j"]
    assert neo4j["image"] == "neo4j:5.26-community"
    assert neo4j["environment"]["NEO4J_AUTH"] == "neo4j/${NEO4J_PASSWORD:-hippo-password}"
    assert "healthcheck" in neo4j
    assert "neo4j_data" in compose["volumes"]
    env = compose["services"]["app"]["environment"]
    assert env["NEO4J_URI"] == "bolt://neo4j:7687"
    # The password comes from .env (written by ./hippo up) and must be the same one Neo4j was started with.
    assert env["NEO4J_PASSWORD"] == "${NEO4J_PASSWORD:-hippo-password}"


def test_compose_ollama_is_optional():
    compose = yaml.safe_load(COMPOSE.read_text())
    ollama = compose["services"]["ollama"]
    assert ollama["profiles"] == ["ollama"]
    assert "ollama_data" in compose["volumes"]


def test_compose_publishes_every_port_on_loopback_only():
    """hippo has no login and Ollama no password: nothing may listen on the LAN by default."""
    compose = yaml.safe_load(COMPOSE.read_text())
    ports = {name: service.get("ports", []) for name, service in compose["services"].items()}
    assert ports["neo4j"] == ["127.0.0.1:7474:7474", "127.0.0.1:7687:7687"]
    assert ports["ollama"] == ["127.0.0.1:11434:11434"]
    # The UI port can be opened on purpose through HIPPO_BIND, but the default is loopback.
    assert ports["app"] == ["${HIPPO_BIND:-127.0.0.1}:8000:8000"]


# ---------------------------------------------------------- dockerfile


def test_dockerfile_builds_a_small_app_image():
    text = DOCKERFILE.read_text()
    assert text.startswith("# ") or text.startswith("FROM")
    assert "FROM python:3.12-slim" in text
    assert "git" in text
    assert "EXPOSE 8000" in text
    assert 'CMD ["hippo", "serve"]' in text
    assert "[dev]" not in text, "dev dependencies do not belong in the image"
    assert '".[neo4j]"' in text, "the image must be able to talk to the optional Neo4j service"


# ------------------------------------------------------------ launcher


def test_launcher_is_valid_bash_and_executable():
    result = subprocess.run(["bash", "-n", str(LAUNCHER)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert os.access(LAUNCHER, os.X_OK), "run: chmod +x hippo"
    text = LAUNCHER.read_text()
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text


def test_launcher_knows_every_subcommand_and_prints_the_urls():
    text = LAUNCHER.read_text()
    for command in ("up", "down", "logs", "pull-models", "test", "ps"):
        assert re.search(rf"^\s*{re.escape(command)}\)", text, re.MULTILINE), f"missing subcommand {command}"
    assert "http://host.docker.internal:11434" in text
    assert "--profile ollama" in text and "--profile neo4j" in text
    for url in ("http://localhost:8000", "http://localhost:7474", "http://localhost:8000/mcp"):
        assert url in text


def test_launcher_help_runs_without_docker():
    """`./hippo help` must not need docker: it is the first thing a stuck person tries."""
    result = subprocess.run(["bash", str(LAUNCHER), "help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "./hippo up" in result.stdout


FAKE_DOCKER = """#!/usr/bin/env bash
# Stands in for docker: records every call, answers "no such volume" unless FAKE_VOLUME_EXISTS=1.
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
if [ "$1 $2" = "volume inspect" ]; then
  [ "${FAKE_VOLUME_EXISTS:-0}" = "1" ] && exit 0 || exit 1
fi
exit 0
"""


@pytest.fixture
def launcher_dir(tmp_path: Path) -> Path:
    """A copy of the launcher next to a fake `docker` (and a `curl` that finds no Ollama), so `up` can run here."""
    shutil.copy(LAUNCHER, tmp_path / "hippo")
    shutil.copy(COMPOSE, tmp_path / "docker-compose.yml")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "curl").write_text("#!/usr/bin/env bash\nexit 1\n")
    for tool in ("docker", "curl"):
        (bin_dir / tool).chmod(0o755)
    return tmp_path


def choose_neo4j(launcher_dir: Path, extra: str = "") -> None:
    """Write a .env that asks for the Neo4j container (the default is the embedded file, no password needed)."""
    (launcher_dir / ".env").write_text("HIPPO_STORE=neo4j\n" + extra)


def run_up(launcher_dir: Path, **env: str) -> subprocess.CompletedProcess:
    full_env = {
        **os.environ,
        "PATH": f"{launcher_dir / 'bin'}:{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(launcher_dir / "docker.log"),
        **env,
    }
    return subprocess.run(
        ["bash", str(launcher_dir / "hippo"), "up"],
        capture_output=True,
        text=True,
        env=full_env,
        cwd=launcher_dir,
    )


def env_password(launcher_dir: Path) -> list[str]:
    return re.findall(r"^NEO4J_PASSWORD=(.*)$", (launcher_dir / ".env").read_text(), re.MULTILINE)


def test_launcher_up_by_default_needs_no_password_and_no_neo4j(launcher_dir: Path):
    result = run_up(launcher_dir)
    assert result.returncode == 0, result.stderr
    assert not (launcher_dir / ".env").exists(), "nothing to write: the embedded store has no password"
    assert "hippo.lbug" in result.stdout and "Neo4j browser" not in result.stdout
    log = (launcher_dir / "docker.log").read_text()
    assert "up -d" in log and "--profile neo4j" not in log
    # No Ollama on this machine (the fake curl fails), so the ollama container is started.
    assert "--profile ollama" in log


def test_launcher_up_starts_neo4j_when_env_asks_for_it(launcher_dir: Path):
    choose_neo4j(launcher_dir)
    result = run_up(launcher_dir)
    assert result.returncode == 0, result.stderr
    assert "--profile neo4j" in (launcher_dir / "docker.log").read_text()
    assert "Neo4j browser" in result.stdout


def test_launcher_up_writes_a_random_password_once_and_prints_it(launcher_dir: Path):
    choose_neo4j(launcher_dir)
    first = run_up(launcher_dir)
    assert first.returncode == 0, first.stderr
    (password,) = env_password(launcher_dir)
    assert re.fullmatch(r"[0-9a-f]{32}", password), "expected 16 random bytes as hex"
    assert password in first.stdout  # the person must see it: the Neo4j browser asks for it
    assert "default password" not in first.stdout

    second = run_up(launcher_dir)  # the same password every time: Neo4j only accepts the first one
    assert second.returncode == 0, second.stderr
    assert env_password(launcher_dir) == [password]
    assert password in second.stdout
    assert "up -d" in (launcher_dir / "docker.log").read_text()  # it did start compose


def test_launcher_up_fills_in_an_empty_password_line_from_env_example(launcher_dir: Path):
    choose_neo4j(launcher_dir, "OLLAMA_URL=http://localhost:11434\nNEO4J_PASSWORD=\n")
    result = run_up(launcher_dir)
    assert result.returncode == 0, result.stderr
    (password,) = env_password(launcher_dir)  # one line, not two
    assert re.fullmatch(r"[0-9a-f]{32}", password)
    assert "OLLAMA_URL=http://localhost:11434" in (launcher_dir / ".env").read_text()


def test_launcher_up_keeps_the_default_password_for_an_existing_database(launcher_dir: Path):
    """A neo4j_data volume made before this change only accepts 'hippo-password'; a new random one would lock us out."""
    choose_neo4j(launcher_dir)
    result = run_up(launcher_dir, FAKE_VOLUME_EXISTS="1")
    assert result.returncode == 0, result.stderr
    assert env_password(launcher_dir) == ["hippo-password"]
    assert "default password" in result.stdout  # and it says so, with a warning


def test_launcher_up_respects_a_password_already_in_env(launcher_dir: Path):
    choose_neo4j(launcher_dir, "NEO4J_PASSWORD=my-own-secret\n")
    result = run_up(launcher_dir)
    assert result.returncode == 0, result.stderr
    assert env_password(launcher_dir) == ["my-own-secret"]
    assert "my-own-secret" in result.stdout


# --------------------------------------------------------- .env.example


def env_vars_read_by_config() -> set[str]:
    """Every `_env("NAME", ...)` call in config.py."""
    return set(re.findall(r'_env\("([A-Z0-9_]+)"', CONFIG.read_text()))


def test_env_example_mentions_every_config_variable():
    names = env_vars_read_by_config()
    assert names, "config.py should read at least one variable through _env()"
    text = ENV_EXAMPLE.read_text()
    missing = [n for n in names if not re.search(rf"^{n}=", text, re.MULTILINE)]
    assert not missing, f".env.example is missing: {missing}"


def test_env_example_leaves_the_neo4j_password_for_the_launcher_to_fill_in():
    """Copying .env.example must not pin the well-known default password: ./hippo up writes a random one."""
    text = ENV_EXAMPLE.read_text()
    assert re.search(r"^NEO4J_PASSWORD=$", text, re.MULTILINE)
    assert "hippo-password" not in text
    assert re.search(r"^HIPPO_BIND=127.0.0.1$", text, re.MULTILINE)
    assert re.search(r"^HIPPO_STORE=ladybug$", text, re.MULTILINE), "the embedded store is the default"


def test_env_example_has_a_comment_for_every_variable():
    """Each variable line should have an explanation somewhere above it (the file is documentation)."""
    lines = ENV_EXAMPLE.read_text().splitlines()
    previous_comment = False
    for line in lines:
        if line.startswith("#"):
            previous_comment = True
        elif "=" in line:
            assert previous_comment, f"{line!r} has no comment above it"
        elif not line.strip():
            previous_comment = False


# ------------------------------------------------------------------ ci


def test_ci_workflow_parses_and_has_the_three_jobs():
    workflow = yaml.safe_load(CI.read_text())
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1); accept both spellings.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None and "push" in triggers and "pull_request" in triggers
    jobs = workflow["jobs"]
    assert set(jobs) == {"lint", "unit", "neo4j"}


def test_ci_runs_the_unit_tests_on_every_store():
    workflow = yaml.safe_load(CI.read_text())
    jobs = workflow["jobs"]
    assert jobs["unit"]["strategy"]["matrix"]["python"] == ["3.11", "3.12"]
    assert jobs["unit"]["strategy"]["matrix"]["store"] == ["ladybug", "fake"]
    assert jobs["unit"]["env"]["HIPPO_TEST_STORE"] == "${{ matrix.store }}"
    unit_runs = [step.get("run", "") for step in jobs["unit"]["steps"]]
    assert any("pytest tests/unit" in run for run in unit_runs)
    neo4j = jobs["neo4j"]
    assert neo4j["env"]["HIPPO_TEST_STORE"] == "neo4j"
    assert neo4j["services"]["neo4j"]["image"] == "neo4j:5.26-community"
    assert neo4j["services"]["neo4j"]["env"]["NEO4J_AUTH"] == "neo4j/hippo-password"
    assert "--health-cmd" in neo4j["services"]["neo4j"]["options"]
    assert neo4j["env"]["NEO4J_URI"] == "bolt://localhost:7687"
    neo4j_runs = [step.get("run", "") for step in neo4j["steps"]]
    assert any("pytest tests/unit" in run for run in neo4j_runs)
    lint_runs = [step.get("run", "") for step in jobs["lint"]["steps"]]
    assert any("ruff check" in run for run in lint_runs)
    assert any("ruff format --check" in run for run in lint_runs)


# ------------------------------------------------------------- the docs


def test_contracts_route_map_lists_every_route_of_the_app(ctx):
    """docs/CONTRACTS.md calls itself the map of the code; every route path must be findable in it."""
    from hippo.web.app import create_app

    def normalised(path: str) -> str:
        return re.sub(
            r"\{[a-z_]+\}", "{id}", path
        )  # the doc writes {id}, the code {source_id}, {run_id}, ...

    contracts = normalised((ROOT / "docs" / "CONTRACTS.md").read_text())
    # The OpenAPI document is the public list of every route with its full (prefixed) path.
    paths = sorted(create_app(ctx).openapi()["paths"])
    assert len(paths) > 40
    missing = [path for path in paths if normalised(path) not in contracts]
    assert not missing, f"routes missing from docs/CONTRACTS.md: {missing}"

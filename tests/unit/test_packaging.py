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
import subprocess
from pathlib import Path

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


def test_compose_wires_the_app_to_neo4j_and_ollama():
    compose = yaml.safe_load(COMPOSE.read_text())
    app = compose["services"]["app"]
    env = app["environment"]
    assert env["NEO4J_URI"] == "bolt://neo4j:7687"
    assert env["NEO4J_PASSWORD"] == "hippo-password"
    assert "OLLAMA_URL" in env
    assert env["HIPPO_DATA_DIR"] == "/app/data"
    assert app["depends_on"]["neo4j"]["condition"] == "service_healthy"
    assert any("host.docker.internal" in h for h in app["extra_hosts"])
    assert "./data:/app/data" in app["volumes"]


def test_compose_neo4j_has_auth_and_healthcheck_and_ollama_is_optional():
    compose = yaml.safe_load(COMPOSE.read_text())
    neo4j = compose["services"]["neo4j"]
    assert neo4j["image"] == "neo4j:5.26-community"
    assert neo4j["environment"]["NEO4J_AUTH"] == "neo4j/hippo-password"
    assert "healthcheck" in neo4j
    assert "neo4j_data" in compose["volumes"]
    ollama = compose["services"]["ollama"]
    assert ollama["profiles"] == ["ollama"]
    assert "ollama_data" in compose["volumes"]


# ---------------------------------------------------------- dockerfile


def test_dockerfile_builds_a_small_app_image():
    text = DOCKERFILE.read_text()
    assert text.startswith("# ") or text.startswith("FROM")
    assert "FROM python:3.12-slim" in text
    assert "git" in text
    assert "EXPOSE 8000" in text
    assert 'CMD ["hippo", "serve"]' in text
    assert "[dev]" not in text, "dev dependencies do not belong in the image"


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
    assert "--profile ollama" in text
    for url in ("http://localhost:8000", "http://localhost:7474", "http://localhost:8000/mcp"):
        assert url in text


def test_launcher_help_runs_without_docker():
    """`./hippo help` must not need docker: it is the first thing a stuck person tries."""
    result = subprocess.run(["bash", str(LAUNCHER), "help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "./hippo up" in result.stdout


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


def test_ci_runs_the_unit_tests_twice_once_against_neo4j():
    workflow = yaml.safe_load(CI.read_text())
    jobs = workflow["jobs"]
    assert jobs["unit"]["strategy"]["matrix"]["python"] == ["3.11", "3.12"]
    unit_runs = [step.get("run", "") for step in jobs["unit"]["steps"]]
    assert any("pytest tests/unit" in run for run in unit_runs)
    neo4j = jobs["neo4j"]
    assert neo4j["services"]["neo4j"]["image"] == "neo4j:5.26-community"
    assert neo4j["services"]["neo4j"]["env"]["NEO4J_AUTH"] == "neo4j/hippo-password"
    assert "--health-cmd" in neo4j["services"]["neo4j"]["options"]
    assert neo4j["env"]["NEO4J_URI"] == "bolt://localhost:7687"
    neo4j_runs = [step.get("run", "") for step in neo4j["steps"]]
    assert any("pytest tests/unit" in run for run in neo4j_runs)
    lint_runs = [step.get("run", "") for step in jobs["lint"]["steps"]]
    assert any("ruff check" in run for run in lint_runs)
    assert any("ruff format --check" in run for run in lint_runs)

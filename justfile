# hippo task runner. `just` lists the recipes.
#
# hippo can keep its graph in two places, and every recipe here says which one it starts:
#
#   just ladybug        docker: the app, with the graph in an embedded LadybugDB file (./data/hippo.lbug)
#   just neo4j          docker: the app plus a Neo4j container for the graph
#   just dev            no docker: `hippo serve` from .venv on the LadybugDB file
#   just dev-neo4j      no docker: `hippo serve` from .venv against a Neo4j at NEO4J_URI
#
# The two stores hold the same graph and pass the same tests. The difference is operational:
# LadybugDB is one file and one process (the CLI talks to the running server); Neo4j is a server
# many processes can share, with its Browser at http://localhost:7474. A memory built in one is not
# moved to the other. Setting HIPPO_STORE in .env picks the default for the plain `just up`.

set shell := ["bash", "-euo", "pipefail", "-c"]

url := "http://localhost:8000"
neo4j_browser := "http://localhost:7474"
venv := ".venv/bin"

# List recipes
default:
    @just --list --unsorted

# ------------------------------------------------------------- docker, LadybugDB

# Start hippo in docker with the embedded LadybugDB store (no database container)
ladybug *args:
    @echo "▶ hippo on LadybugDB (embedded file ./data/hippo.lbug), in docker"
    HIPPO_STORE=ladybug ./hippo up {{args}}

# Same, rebuilding the app image first
ladybug-build:
    @just ladybug --build

# ---------------------------------------------------------------- docker, Neo4j

# Start hippo in docker with a Neo4j container for the graph (browser at http://localhost:7474)
neo4j *args:
    @echo "▶ hippo on Neo4j (container, browser at {{neo4j_browser}}), in docker"
    HIPPO_STORE=neo4j ./hippo up {{args}}

# Same, rebuilding the app image first
neo4j-build:
    @just neo4j --build

# Start only the Neo4j container (for `just dev-neo4j`, or to browse an existing graph)
neo4j-db:
    @echo "▶ Neo4j container only (bolt://localhost:7687, browser at {{neo4j_browser}})"
    docker compose --profile neo4j up -d neo4j

# ------------------------------------------------------ docker, either backend

# Start whatever HIPPO_STORE in .env says (LadybugDB when it says nothing)
up *args:
    ./hippo up {{args}}

# Stop everything, whichever backend is running (data stays in ./data and the docker volumes)
down:
    ./hippo down

# Follow the app's logs
logs:
    ./hippo logs

# Show what is running (tells you which backend by the containers you see)
ps:
    ./hippo ps

# Download the LLM and embedding model into Ollama
pull-models:
    ./hippo pull-models

# Run the hippo CLI inside the container, e.g. `just cli ask "Who designed the Orion arm?"`
cli *args:
    ./hippo {{args}}

# List users and roles (the access ladder); add one with `just cli user add <name> --role <role>`
users:
    ./hippo users

# Open the UI in the default browser
open:
    open {{url}}

# Wait until the UI answers, then print the address
wait:
    @for i in $(seq 1 60); do \
        if curl -sf -o /dev/null {{url}}; then echo "hippo is up at {{url}}"; exit 0; fi; \
        sleep 2; \
    done; \
    echo "hippo did not answer at {{url}} within 2 minutes; try: just logs" >&2; exit 1

# `just ladybug` and wait until the UI answers
start-ladybug: ladybug wait

# `just neo4j` and wait until the UI answers
start-neo4j: neo4j wait

# --------------------------------------------------------------- without docker

# Make .venv with hippo, the dev tools and the Neo4j driver (needs Python 3.11+)
venv:
    test -d .venv || python3 -m venv .venv
    {{venv}}/pip install -q -e ".[dev,neo4j]"
    @echo "ok: {{venv}}/hippo is ready"

# Run `hippo serve` from .venv on the embedded LadybugDB file (HIPPO_DATA_DIR/hippo.lbug); Ollama must be running
dev *args:
    @echo "▶ hippo serve on LadybugDB (embedded file), from .venv"
    HIPPO_STORE=ladybug {{venv}}/hippo serve {{args}}

# Run `hippo serve` from .venv against a Neo4j at NEO4J_URI (start one with `just neo4j-db`)
dev-neo4j *args:
    @echo "▶ hippo serve on Neo4j (NEO4J_URI=${NEO4J_URI:-bolt://localhost:7687}), from .venv"
    HIPPO_STORE=neo4j {{venv}}/hippo serve {{args}}

# The local CLI, e.g. `just hippo sources`; while `just dev` runs it talks to that server (set HIPPO_TOKEN once users exist)
hippo *args:
    {{venv}}/hippo {{args}}

# ----------------------------------------------------------------------- tests

# Unit tests on the embedded LadybugDB store (a fresh file per test; the default in CI too)
test:
    HIPPO_TEST_STORE=ladybug {{venv}}/python -m pytest tests/unit

# Unit tests on the in-memory fake store (quickest)
test-fake:
    HIPPO_TEST_STORE=fake {{venv}}/python -m pytest tests/unit

# Unit tests against a real Neo4j in a throwaway container (needs docker; port 17687)
test-neo4j:
    @docker rm -f hippo-neo4j-test >/dev/null 2>&1 || true
    docker run -d --rm --name hippo-neo4j-test -p 127.0.0.1:17687:7687 -p 127.0.0.1:17474:7474 \
        -e NEO4J_AUTH=neo4j/hippo-password neo4j:5.26-community >/dev/null
    @for i in $(seq 1 40); do curl -sf -o /dev/null http://localhost:17474 && break; sleep 3; done
    HIPPO_TEST_STORE=neo4j NEO4J_URI=bolt://localhost:17687 NEO4J_PASSWORD=hippo-password \
        {{venv}}/python -m pytest tests/unit || (docker stop hippo-neo4j-test >/dev/null; exit 1)
    docker stop hippo-neo4j-test >/dev/null

# The same suite on all three stores, as CI runs it
test-all: test test-fake test-neo4j

# Unit tests inside a throwaway app container (docker; no local Python needed)
test-docker:
    ./hippo test

# ruff check + format check
lint:
    {{venv}}/ruff check .
    {{venv}}/ruff format --check .

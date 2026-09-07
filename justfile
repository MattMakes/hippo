# hippo task runner. `just` lists recipes; `just up` starts everything.
# Most recipes delegate to ./hippo, the docker compose launcher.

set shell := ["bash", "-euo", "pipefail", "-c"]

url := "http://localhost:8000"

# List recipes
default:
    @just --list --unsorted

# Start Neo4j, the app and (if this machine has no Ollama) an Ollama container
up *args:
    ./hippo up {{args}}

# Rebuild the app image and start everything
build:
    ./hippo up --build

# Stop everything (data stays in the docker volumes)
down:
    ./hippo down

# Stop and start again
restart: down up

# Follow the app's logs
logs:
    ./hippo logs

# Show what is running
ps:
    ./hippo ps

# Download the LLM and embedding model into Ollama
pull-models:
    ./hippo pull-models

# Run the unit tests inside a throwaway app container
test:
    ./hippo test

# Run the hippo CLI inside the container, e.g. `just cli ask "Who designed the Orion arm?"`
cli *args:
    ./hippo {{args}}

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

# Start everything and wait until the UI answers
start: up wait

# List users and roles (the access ladder); add one with `just cli user add <name> --role <role>`
users:
    ./hippo users

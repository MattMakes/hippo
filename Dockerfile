# The hippo app image: the FastAPI UI, the MCP endpoint and the `hippo` CLI.
# Neo4j and Ollama run in their own containers (see docker-compose.yml).
FROM python:3.12-slim

# git is the only system package we need: "index a git URL" clones with it.
# Cleaning apt's cache afterwards keeps the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Only what the package needs to build and run (no tests, no dev tools).
COPY pyproject.toml README.md ./
COPY src ./src
COPY samples ./samples

# Install hippo itself; this also creates the `hippo` command.
RUN pip install --no-cache-dir .

# Uploads, cloned repos and other runtime files live here (docker-compose mounts ./data on it).
ENV HIPPO_DATA_DIR=/app/data
RUN mkdir -p /app/data

EXPOSE 8000
CMD ["hippo", "serve"]

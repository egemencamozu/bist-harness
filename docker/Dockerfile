# Harness + Streamlit UI image. Data (data/db) and the model (models/) are mounted, never baked in.
# Build/run through docker-compose.yml at the project root (README.md).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    BISTHARNESS_ROOT=/app

WORKDIR /app

# dependencies first (cached layer), then the project itself
COPY pyproject.toml uv.lock CLAUDE.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra llm --extra ui --extra mcp

COPY src ./src
COPY config ./config
COPY eval ./eval
RUN uv sync --frozen --no-dev --extra llm --extra ui --extra mcp

EXPOSE 8501
CMD ["uv", "run", "--no-sync", "streamlit", "run", "src/bistharness/ui/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", \
     "--browser.gatherUsageStats=false"]

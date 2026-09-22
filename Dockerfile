FROM python:3.11-slim

# fonts-dejavu-core: a real TTF for the generated ePub cover. Without it,
# pipeline/epub_builder.py falls back to Pillow's bundled bitmap font, which
# is missing glyphs for characters like "—" (see docs/TASKS.md Phase 5).
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
ENV PYTHONPATH=/app \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

# Install dependencies first so this layer caches across code-only changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
COPY connectors ./connectors
COPY pipeline ./pipeline
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
RUN uv sync --locked --no-dev

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

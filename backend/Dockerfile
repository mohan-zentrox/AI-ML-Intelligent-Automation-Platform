# Project Synapse - backend container image
FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps needed by psycopg2 (and optionally chromadb's sqlite build).
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Default (zero-dependency) local dev / CI path does not need chromadb or
# litellm installed - see app/services/vector_store.py and
# app/services/llm_provider.py for the graceful-fallback / opt-in behaviour.
# The container image installs everything so the pluggable providers can be
# switched on purely via environment variables at runtime.
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

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

# Two requirement files, installed in separate layers: the core set is what
# the default LLM_PROVIDER=mock / VECTOR_STORE_BACKEND=inmemory path needs, and
# the optional set adds the chromadb/litellm backends so they can be switched
# on with nothing but an environment variable at runtime.
#
# Set INSTALL_OPTIONAL_PROVIDERS=false for a much smaller image when you know
# you will run the default providers (the optional set pulls in onnxruntime,
# boto3, tokenizers and friends).
ARG INSTALL_OPTIONAL_PROVIDERS=true
COPY requirements.txt requirements-optional.txt ./
RUN pip install -r requirements.txt     && if [ "$INSTALL_OPTIONAL_PROVIDERS" = "true" ]; then          pip install -r requirements-optional.txt;        fi

COPY . .

EXPOSE 8000

# Most free/managed hosts (Render, Fly, Cloud Run, HF Spaces) inject the port to
# listen on via $PORT rather than letting the image choose, so honour it and
# fall back to 8000 for plain `docker run`. Shell form is required for the
# variable to be expanded.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

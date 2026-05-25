# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary from the official image — no pip install needed.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy only the dependency manifest first so the install layer is only
# invalidated when dependencies change, not on every source code edit.
COPY pyproject.toml README.md ./

# Minimal stub so the editable install can run without the full source tree.
# The .pth link means the real source copied below is picked up at import time.
RUN mkdir -p app && touch app/__init__.py

# uv is 10-100x faster than pip. The cache mount persists downloaded wheels
# across builds so packages are never re-fetched from the network.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -e ".[web]"

# Copy source after deps are installed. Code changes only invalidate these
# COPY layers — the install step above is not re-triggered.
COPY app ./app
COPY migrations ./migrations
COPY web ./web

EXPOSE 8000

CMD ["uvicorn", "web.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]

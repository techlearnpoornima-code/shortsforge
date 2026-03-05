# ─────────────────────────────────────────────────────────────
#  ShortsForge AI — Production Dockerfile
#  Base: python:3.12-slim (minimal attack surface)
#  Target: Google Cloud Run Jobs
# ─────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

# Metadata
LABEL maintainer="ShortsForge AI"
LABEL description="LangGraph YouTube Shorts automation pipeline"
LABEL version="2.0"

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
# - ffmpeg: in case video post-processing is needed
# - curl: used by entrypoint health checks
# - google-cloud-sdk: for fetching secrets from Secret Manager at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    gnupg \
    apt-transport-https \
    ca-certificates \
    && echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] \
       https://packages.cloud.google.com/apt cloud-sdk main" \
       | tee /etc/apt/sources.list.d/google-cloud-sdk.list \
    && curl https://packages.cloud.google.com/apt/doc/apt-key.gpg \
       | apt-key --keyring /usr/share/keyrings/cloud.google.gpg add - \
    && apt-get update && apt-get install -y --no-install-recommends \
       google-cloud-cli \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Dependency layer (cached unless requirements.txt changes) ─
FROM base AS deps

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application layer ─────────────────────────────────────────
FROM deps AS app

WORKDIR /app

# Copy source code
COPY graph/           ./graph/
COPY main.py          .
COPY entrypoint.sh    .
COPY .env.example     .

# Create output directories (videos + metadata saved here during run)
RUN mkdir -p output/videos output/metadata

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Run as non-root user for security
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

# Cloud Run Jobs don't need an exposed port
# CMD is overridden by entrypoint.sh
CMD ["./entrypoint.sh"]

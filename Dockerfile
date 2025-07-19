# Dockerfile for Gentlebot on Raspberry Pi
# Uses Python 3 on Debian with a multi-stage build

# Ensure builder runs per-target architecture
ARG BUILDPLATFORM
FROM --platform=$BUILDPLATFORM python:3.11-slim-bookworm AS builder

# Install build tools and libs needed to compile wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential python3-dev libatlas-base-dev libffi-dev \
    libssl-dev libjpeg-dev libopenjp2-7 libtiff6 postgresql-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./

# Compile hashed-lock and wheelhouse
RUN pip install --no-cache-dir pip==24.0 'pip-tools<7.0' \
 && pip-compile --allow-unsafe --generate-hashes --output-file=requirements.lock requirements.txt \
 && pip wheel --wheel-dir=/wheels --only-binary=:all: -r requirements.lock

# Stage 2: minimal runtime image
FROM python:3.11-slim-bookworm

# Install only runtime libs and postgres client
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client libatlas3-base libffi8 libssl3 \
    libjpeg62-turbo libopenjp2-7 libtiff6 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy lockfile first (cache bust), then wheelhouse
COPY --from=builder /app/requirements.lock ./
COPY --from=builder /wheels /wheels

# Install from wheelhouse with hashes
RUN pip install --no-cache-dir --require-hashes --no-index --find-links=/wheels -r requirements.lock

# Copy application code
COPY . .
RUN chmod +x scripts/start.sh

# Production env and minimal pip noise
ENV env=PROD
ENV LOG_LEVEL=INFO
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV DOCKER_PRUNE=1

# Healthcheck for container orchestration
HEALTHCHECK CMD python -m gentlebot.version || exit 1

ENTRYPOINT ["/app/scripts/start.sh"]

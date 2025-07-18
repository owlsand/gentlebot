# Dockerfile for Gentlebot on Raspberry Pi
# Uses Python 3 on Debian with a multi-stage build

# Ensure builder runs per-target architecture
ARG BUILDPLATFORM
FROM --platform=$BUILDPLATFORM python:3.11-slim-bookworm AS builder

# Install build tools and libs needed to compile wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential python3-dev libatlas-base-dev libffi-dev libssl-dev \
    libjpeg-dev libopenjp2-7 libtiff6 libpng-dev libfreetype6-dev zlib1g-dev \
    libpq-dev postgresql-client rustc cargo \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./

# 1. Install pip-tools for locking
RUN pip install --no-cache-dir pip==24.0 wheel 'pip-tools<7.0'

# 2. Generate unhashed dependency list
RUN pip-compile --allow-unsafe --output-file=requirements.unhashed.txt requirements.txt

# 3. Build wheels for all dependencies
RUN pip wheel --wheel-dir=/wheels --only-binary=:all: -r requirements.unhashed.txt

# 4. Generate hashed lockfile using local wheels
RUN PIP_FIND_LINKS=/wheels pip-compile --allow-unsafe --generate-hashes \
    --find-links /wheels --output-file=requirements.lock requirements.unhashed.txt

# Debug: inspect wheelhouse
RUN echo "[DEBUG] /wheels contents:" && ls -AlR /wheels && \
    echo "[DEBUG] Peewee SHA256:" && sha256sum /wheels/peewee-3.18.2-py3-none-any.whl

# Stage 2: runtime
FROM python:3.11-slim-bookworm AS runtime

# Install only runtime libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client libatlas3-base libffi8 libssl3 \
    libjpeg62-turbo libopenjp2-7 libtiff6 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/requirements.lock ./
COPY --from=builder /wheels /wheels

# Install from wheelhouse with hash verification
RUN pip install --no-cache-dir --require-hashes --no-index --find-links=/wheels \
    -r requirements.lock

COPY . .
RUN chmod +x scripts/start.sh

ENV env=PROD
ENV LOG_LEVEL=INFO
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV DOCKER_PRUNE=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
    CMD python -m gentlebot.version || exit 1

ENTRYPOINT ["/app/scripts/start.sh"]

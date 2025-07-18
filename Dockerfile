# Dockerfile for Gentlebot on Raspberry Pi
# Uses Python 3 on Debian with a multi-stage build

# Stage 1: build wheels and lock dependencies with hashes
FROM python:3.11-slim-bookworm AS builder

# Install build tools and libraries required by Pillow and Matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libatlas-base-dev \
    libffi-dev \
    libssl-dev \
    libjpeg-dev \
    libopenjp2-7 \
    libtiff6 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create hashed requirements and wheelhouse
COPY requirements.txt ./
RUN pip install --no-cache-dir pip==24.0 pip-tools<7.0 \
    && pip-compile --generate-hashes --output-file=requirements.lock requirements.txt \
    && pip wheel --wheel-dir=/wheels -r requirements.lock

# Stage 2: minimal runtime image
FROM python:3.11-slim-bookworm

# Install only runtime libraries and pg_isready
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    libatlas3-base \
    libffi8 \
    libssl3 \
    libjpeg62-turbo \
    libopenjp2-7 \
    libtiff6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packages from wheels using hashes
COPY --from=builder /wheels /wheels
COPY --from=builder /app/requirements.lock ./
RUN pip install --no-cache-dir --require-hashes --no-index --find-links=/wheels -r requirements.lock

# Copy source code
COPY . .
RUN chmod +x scripts/start.sh

# Set default environment to production and limit console logging to INFO
ENV env=PROD
ENV LOG_LEVEL=INFO

ENV DOCKER_PRUNE=0
ENTRYPOINT ["/app/scripts/start.sh"]

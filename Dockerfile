# Use Debian‑slim + Python 3.11
FROM python:3.11-slim-bookworm

# Install both build‑time and run‑time libs
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential python3-dev libatlas-base-dev libffi-dev libssl-dev \
      libjpeg-dev libopenjp2-7 libtiff6 libpng-dev libfreetype6-dev zlib1g-dev \
      libpq-dev postgresql-client rustc cargo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy your top‑level requirements and lock/install in one go
COPY requirements.txt ./

# 1) Install pip‑tools + wheel
# 2) Compile unhashed, build wheels for all arches
# 3) Compile hashed lockfile against /wheels
# 4) Install hashed deps from /wheels
RUN pip install --no-cache-dir pip==24.0 wheel pip-tools && \
    pip-compile --allow-unsafe --output-file=requirements.unhashed.txt requirements.txt && \
    pip wheel --wheel-dir=/wheels -r requirements.unhashed.txt && \
    PIP_FIND_LINKS=/wheels pip-compile --allow-unsafe \
      --generate-hashes --find-links /wheels \
      --output-file=requirements.lock requirements.unhashed.txt && \
    PIP_FIND_LINKS=/wheels pip install --no-cache-dir \
      --require-hashes --no-index --find-links=/wheels \
      -r requirements.lock && \
    rm -rf /wheels requirements.unhashed.txt requirements.lock

# Copy your app code
COPY . .

RUN chmod +x scripts/start.sh

# Env & healthcheck
ENV env=PROD
ENV LOG_LEVEL=INFO
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
    CMD python -m gentlebot.version || exit 1

ENTRYPOINT ["/app/scripts/start.sh"]

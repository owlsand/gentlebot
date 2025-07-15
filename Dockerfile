# Dockerfile for Gentlebot on Raspberry Pi
# Uses Python 3 on Debian and installs system build deps

# Use the official multi-arch Python image so the Docker build works for both
# amd64 and arm64 targets. The previous arm64v8-only image caused build errors
# when GitHub Actions attempted to build for multiple platforms.
FROM python:3.11-slim-bookworm

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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Set default environment to production and limit console logging to INFO
ENV env=PROD
ENV LOG_LEVEL=INFO

CMD ["python", "-m", "gentlebot"]

# Dockerfile for Gentlebot on Raspberry Pi
# Uses Python 3 on Debian and installs system build deps

FROM arm64v8/python:3.11-slim-bookworm

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
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir python-dateutil pytz beautifulsoup4 \
        yfinance matplotlib pandas huggingface-hub watchdog

# Copy source code
COPY . .

# Set default environment to production
ENV env=PROD

CMD ["python", "main.py"]

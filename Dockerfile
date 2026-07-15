# Crawlr container image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CRAWLR_DATA_DIR=/data

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY crawlr ./crawlr

# Include the Postgres extra so the image can talk to the compose db service.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[postgres]"

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# Default: serve the dashboard. Override the command to run `crawlr monitor --daemon`.
CMD ["crawlr", "serve", "--host", "0.0.0.0", "--port", "8000"]

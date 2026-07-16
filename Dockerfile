# Crawlr — self-healing web scraper. Runs the dashboard by default.
#
#   docker build -t crawlr .
#   docker run -p 8000:8000 -v crawlr-data:/data crawlr
#
# Then open http://localhost:8000
FROM python:3.12-slim

# Keep Python lean and unbuffered for clean container logs.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CRAWLR_DATA_DIR=/data

WORKDIR /app

# Install the package. Copy only what the build backend needs first so Docker
# can cache the dependency layer across code-only changes.
COPY pyproject.toml README.md LICENSE ./
COPY crawlr ./crawlr
RUN pip install .

# Persist the SQLite database, selector cache, and snapshots across restarts.
VOLUME ["/data"]
EXPOSE 8000

CMD ["crawlr", "serve", "--host", "0.0.0.0", "--port", "8000"]

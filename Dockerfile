# Playwright's official image ships matching browsers + system deps.
# Tag MUST match the locked playwright version (see uv.lock).
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

# uv binary, no pip anywhere.
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

# Update OS packages to fix OpenSSL (CVE-2026-45447) and GStreamer (CVE-2025-3887)
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Layer deps separately from source for caching.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# Run as the image's non-root user; bind all interfaces inside the container
# (the shared bearer token is what protects the endpoint — set SCRAPER_AUTH_TOKEN).
USER pwuser
ENV SCRAPER_HOST=0.0.0.0 \
    SCRAPER_PORT=8000 \
    SCRAPER_TRANSPORT=http \
    PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

CMD ["web-scraper-mcp"]

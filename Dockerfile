FROM python:3.12-slim-bookworm

# Add uv
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Layer deps separately from source for caching.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# Install ONLY the OS dependencies required by Chromium
RUN .venv/bin/playwright install-deps chromium \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m pwuser && chown -R pwuser:pwuser /app
USER pwuser

# Install Chromium as the non-root user (so it's in their ~/.cache)
RUN .venv/bin/playwright install chromium

ENV SCRAPER_HOST=0.0.0.0 \
    SCRAPER_PORT=8000 \
    SCRAPER_TRANSPORT=http \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["web-scraper-mcp"]

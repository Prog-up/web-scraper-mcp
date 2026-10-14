FROM python:3.14-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

# Add uv
COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:77280f2f771df71f90786c314fe1bbc1e023feac652969bbf139c280babf2eb7 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Layer deps separately from source for caching.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# Install browser libraries, remove unused X server/printing packages, and
# apply available Debian security updates. libgbm requires Debian's Mesa libraries.
RUN apt-get update \
    && apt-get upgrade -y \
    && .venv/bin/playwright install-deps chromium \
    && apt-get purge -y --auto-remove xvfb xserver-common mesa-vulkan-drivers libcups2t64 \
    && apt-get upgrade -y \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' perl-base)" ge "5.36.0-7+deb12u4" \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m pwuser && chown -R pwuser:pwuser /app
USER pwuser

# Install Chromium as the non-root user (so it's in their ~/.cache)
RUN .venv/bin/playwright install chromium --only-shell

ENV PYTHONDONTWRITEBYTECODE=1 \
    SCRAPER_HOST=0.0.0.0 \
    SCRAPER_PORT=8000 \
    SCRAPER_TRANSPORT=http \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["web-scraper-mcp"]

"""Runtime settings — all overridable via env (prefix SCRAPER_) or a .env file.

External API keys keep their conventional names (ANTHROPIC_API_KEY, ...) so they
work without a prefix.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCRAPER_", env_file=".env", extra="ignore")

    # --- server / transport ---
    host: str = "127.0.0.1"
    port: int = 8000
    # Shared bearer token for the HTTP endpoint. If unset, the endpoint is
    # UNAUTHENTICATED (a warning is logged) — only acceptable for stdio/local.
    auth_token: str | None = None

    # --- resource caps (protect the box from OOM/DoS) ---
    max_response_bytes: int = 5_000_000
    request_timeout_s: float = 30.0
    max_concurrent_pages: int = 8
    max_crawl_pages: int = 100
    max_crawl_depth: int = 3
    per_domain_delay_s: float = 1.0
    max_redirects: int = 5

    # --- politeness / anti-bot (self-hosted) ---
    user_agent: str = "web-scraper-mcp/0.1 (+https://gitlab.cri.epita.fr/enzo.juhel/web-scraper)"
    respect_robots: bool = True
    # SSRF: keep False in any networked deployment. Only flip for local testing.
    allow_private_networks: bool = False

    # --- LLM (extract / deep_research) ---
    anthropic_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY")
    )
    extract_model: str = "claude-haiku-4-5-20251001"
    research_model: str = "claude-sonnet-4-6"

    # --- search backends (first configured wins; else ddgs) ---
    searxng_url: str | None = None
    brave_api_key: str | None = Field(default=None, validation_alias=AliasChoices("BRAVE_API_KEY"))
    tavily_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("TAVILY_API_KEY")
    )


settings = Settings()

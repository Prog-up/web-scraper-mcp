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
    respect_robots: bool = False

    # SSRF: keep False in any networked deployment. Only flip for local testing.
    allow_private_networks: bool = False

    # --- LLM (extract / deep_research / Ollama) ---
    ollama_host: str = Field(
        default="127.0.0.1:11434",
        validation_alias=AliasChoices("OLLAMA_HOST", "SCRAPER_OLLAMA_HOST"),
    )
    anthropic_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY")
    )
    extract_model: str = "llama3.1"
    research_model: str = "llama3.1"

    def ollama_url(self, path: str) -> str:
        host = self.ollama_host or "127.0.0.1:11434"
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        from urllib.parse import urlparse

        parsed = urlparse(host)
        if ":" not in parsed.netloc:
            host = f"{host}:11434"
        return f"{host.rstrip('/')}{path}"

    # --- search backends (first configured wins; else ddgs) ---
    searxng_url: str | None = None
    brave_api_key: str | None = Field(default=None, validation_alias=AliasChoices("BRAVE_API_KEY"))
    tavily_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("TAVILY_API_KEY")
    )


settings = Settings()

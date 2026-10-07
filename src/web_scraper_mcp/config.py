"""Runtime settings — all overridable via env (prefix SCRAPER_) or a .env file.

External API keys keep their conventional names (ANTHROPIC_API_KEY, ...) so they
work without a prefix.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCRAPER_", env_file=".env", extra="ignore", populate_by_name=True
    )

    # --- server / transport ---
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    transport: Literal["http", "stdio"] = "http"
    # HTTP always requires a token; stdio does not.
    auth_token: str | None = Field(default=None, repr=False)

    # --- resource caps (protect the box from OOM/DoS) ---
    max_response_bytes: int = Field(default=5_000_000, ge=1024, le=20_000_000)
    max_request_bytes: int = Field(default=256_000, ge=1024, le=1_000_000)
    request_timeout_s: float = Field(default=30.0, gt=0, le=120)
    tool_timeout_s: float = Field(default=180.0, gt=0, le=600)
    max_concurrent_pages: int = Field(default=4, ge=1, le=16)
    max_concurrent_fetches: int = Field(default=8, ge=1, le=32)
    max_concurrent_tools: int = Field(default=8, ge=1, le=32)
    max_concurrent_llm: int = Field(default=2, ge=1, le=8)
    max_crawl_pages: int = Field(default=100, ge=1, le=1000)
    max_crawl_depth: int = Field(default=3, ge=0, le=10)
    crawl_concurrency: int = Field(default=3, ge=1, le=8)
    max_crawl_jobs: int = Field(default=16, ge=1, le=32)
    max_concurrent_crawls: int = Field(default=2, ge=1, le=4)
    crawl_timeout_s: float = Field(default=180, gt=0, le=600)
    crawl_ttl_s: float = Field(default=600, gt=0, le=86400)
    crawl_result_bytes: int = Field(default=5_000_000, ge=1024, le=20_000_000)
    crawl_frontier_limit: int = Field(default=1000, ge=1, le=5000)
    max_browser_sessions: int = Field(default=2, ge=1, le=8)
    browser_session_ttl_s: float = Field(default=300, gt=0, le=3600)
    browser_snapshot_bytes: int = Field(default=64_000, ge=1024, le=256_000)
    browser_stealth: bool = True
    per_domain_delay_s: float = Field(default=1.0, ge=0, le=60)
    max_redirects: int = Field(default=5, ge=0, le=10)
    cache_entries: int = Field(default=512, ge=1, le=4096)
    cache_ttl_s: float = Field(default=300, gt=0, le=86400)
    browser_enabled: bool = False
    egress_proxy_url: str | None = None
    egress_bind: str = "127.0.0.1"
    browser_resource_limit: int = Field(default=100, ge=1, le=500)
    browser_total_bytes: int = Field(default=20_000_000, ge=1024, le=100_000_000)
    browser_ready_timeout_s: float = Field(default=3, gt=0, le=10)
    llm_input_bytes: int = Field(default=16_000, ge=1024, le=100_000)
    llm_output_tokens: int = Field(default=2048, ge=1, le=8192)
    ollama_num_ctx: int = Field(default=32768, ge=8192, le=131072)
    # Short extraction/research tasks should leave the output budget for answers.
    # None delegates to models whose thinking control cannot be disabled.
    ollama_think: bool | None = False

    @field_validator("ollama_think", mode="before")
    @classmethod
    def empty_thinking_uses_model_default(cls, value):
        return None if value == "" else value

    # --- politeness / anti-bot (self-hosted) ---
    user_agent: str = "web-scraper-mcp (+https://github.com/Prog-up/web-scraper-mcp)"
    respect_robots: bool = True

    # SSRF: keep False in any networked deployment. Only flip for local testing.
    allow_private_networks: bool = False

    # --- LLM (extract / deep_research / Ollama) ---
    ollama_host: str = Field(
        default="127.0.0.1:11434",
        validation_alias=AliasChoices("OLLAMA_HOST", "SCRAPER_OLLAMA_HOST"),
    )
    anthropic_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY"), repr=False
    )
    extract_model: str = "llama3.1"
    research_model: str = "llama3.1"
    extract_provider: Literal["auto", "anthropic", "ollama"] = "auto"
    research_provider: Literal["auto", "anthropic", "ollama"] = "auto"

    def ollama_url(self, path: str) -> str:
        host = self.ollama_host or "127.0.0.1:11434"
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        parsed = urlsplit(host)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("invalid Ollama endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Ollama endpoint must not contain credentials, query or fragment")
        hostname = parsed.hostname
        authority = f"[{hostname}]" if ":" in hostname else hostname
        authority += f":{parsed.port or 11434}"
        return urlunsplit((parsed.scheme, authority, parsed.path.rstrip("/") + path, "", ""))

    # --- search backends (first configured wins; else ddgs) ---
    searxng_url: str | None = None
    brave_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("BRAVE_API_KEY"), repr=False
    )
    tavily_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("TAVILY_API_KEY"), repr=False
    )


settings = Settings()

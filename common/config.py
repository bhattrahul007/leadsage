from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    temperature: float = 0.1
    num_predict: int = 2048
    timeout: int = 120


class OpenAICompatibleConfig(BaseModel):
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    temperature: float = 0.1
    timeout: int = 60


class OpenAIConfig(BaseModel):
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4o-mini"
    temperature: float = 0.1
    timeout: int = 60

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


class GroqConfig(BaseModel):
    api_key_env: str = "GROQ_API_KEY"
    base_url: str = "https://api.groq.com/openai/v1"
    temperature: float = 0.1
    timeout: int = 30

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


class TogetherConfig(BaseModel):
    api_key_env: str = "TOGETHER_API_KEY"
    base_url: str = "https://api.together.xyz/v1"
    temperature: float = 0.1
    timeout: int = 60

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


class AnthropicConfig(BaseModel):
    api_key_env: str = "ANTHROPIC_API_KEY"
    model: str = "claude-3-haiku-20240307"
    temperature: float = 0.1
    timeout: int = 60

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


class PerAgentOverride(BaseModel):
    temperature: float | None = None
    num_predict: int | None = None
    timeout: int | None = None
    timeout_budget_s: int | None = None  # wall-clock budget for one LLM call


class LLMModelsConfig(BaseModel):
    icp_parser: str = "qwen2.5:3b"
    lead_scorer: str = "qwen2.5:7b"
    outreach: str = "qwen2.5:7b"
    contact_finder: str = "qwen2.5:3b"
    research: str = "qwen2.5:7b"
    embedder: str = "nomic-embed-text"


class LLMConfig(BaseModel):
    provider: Literal["ollama", "openai", "openai_compatible", "groq", "together", "anthropic"] = (
        "ollama"
    )
    models: LLMModelsConfig = Field(default_factory=LLMModelsConfig)
    per_agent_overrides: dict[str, PerAgentOverride] = Field(default_factory=dict)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openai_compatible: OpenAICompatibleConfig = Field(default_factory=OpenAICompatibleConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    groq: GroqConfig = Field(default_factory=GroqConfig)
    together: TogetherConfig = Field(default_factory=TogetherConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)

    def get_agent_override(self, agent_name: str) -> PerAgentOverride:
        return self.per_agent_overrides.get(agent_name, PerAgentOverride())


class EmbeddingOllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"


class EmbeddingOpenAIConfig(BaseModel):
    model: str = "text-embedding-3-small"
    api_key_env: str = "OPENAI_API_KEY"

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


class EmbeddingConfig(BaseModel):
    enabled: bool = False
    provider: Literal["ollama", "openai"] = "ollama"
    model: str = "nomic-embed-text"
    dimensions: int = 768
    batch_size: int = 32
    cache_embeddings: bool = True
    similarity_threshold: float = 0.8
    ollama: EmbeddingOllamaConfig = Field(default_factory=EmbeddingOllamaConfig)
    openai: EmbeddingOpenAIConfig = Field(default_factory=EmbeddingOpenAIConfig)


class LinkedSourceSettings(BaseModel):
    enabled: bool = True
    max_results: int = 20


class LinkedSourcesConfig(BaseModel):
    enabled: bool = True
    yc: LinkedSourceSettings = Field(
        default_factory=lambda: LinkedSourceSettings(enabled=True, max_results=20)
    )
    github: LinkedSourceSettings = Field(
        default_factory=lambda: LinkedSourceSettings(enabled=False, max_results=10)
    )
    producthunt: LinkedSourceSettings = Field(
        default_factory=lambda: LinkedSourceSettings(enabled=False, max_results=10)
    )
    crunchbase: LinkedSourceSettings = Field(
        default_factory=lambda: LinkedSourceSettings(enabled=False, max_results=15)
    )


class PipelineSettings(BaseModel):
    providers: list[str] = Field(default_factory=list)
    crawler_type: str = "requests"
    max_results_per_query: int = 10
    search_workers: int = 8
    crawl_enabled: bool = True
    max_urls_to_crawl: int = 50
    crawl_workers: int = 15
    crawl_timeout: int = 20
    domain_delay: float = 0.0
    enrich_enabled: bool = True
    min_lead_score: float = 0.15
    search_cache_ttl: int = 3600
    pages_per_domain: int = 1  # expand to N signal pages per domain
    signal_paths: list[str] = Field(
        default_factory=lambda: ["/", "/about", "/careers", "/technology"]
    )
    linked_sources: LinkedSourcesConfig = Field(default_factory=LinkedSourcesConfig)
    skip_domains: list[str] = Field(
        default_factory=lambda: [
            "youtube.com",
            "twitter.com",
            "x.com",
            "facebook.com",
            "instagram.com",
            "tiktok.com",
            "reddit.com",
            "wikipedia.org",
            "linkedin.com",
        ]
    )
    prefer_domains: list[str] = Field(
        default_factory=lambda: [
            "crunchbase.com",
            "glassdoor.com",
            "builtwith.com",
            "stackshare.io",
            "techcrunch.com",
            "ycombinator.com",
            "producthunt.com",
            "github.com",
        ]
    )

    @field_validator("min_lead_score")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class StaticProxySettings(BaseModel):
    proxies: list[str] = Field(default_factory=list)
    quarantine_seconds: float = 300.0


class BrightDataSettings(BaseModel):
    host: str = "brd.superproxy.io"
    port: int = 22225
    username: str = ""
    password: str = ""
    country: str = "us"
    session_rotation: str = "per_request"


class SmartProxySettings(BaseModel):
    username: str = ""
    password: str = ""
    endpoint: str = "gate.smartproxy.com"
    port: int = 10000
    country: str = ""


class ProxyConfig(BaseModel):
    enabled: bool = False
    provider: str = "none"
    static: StaticProxySettings = Field(default_factory=StaticProxySettings)
    brightdata: BrightDataSettings = Field(default_factory=BrightDataSettings)
    smartproxy: SmartProxySettings = Field(default_factory=SmartProxySettings)

    def get_provider_kwargs(self, name: str) -> dict[str, Any]:
        if name == "static":
            return {
                "proxy_urls": self.static.proxies,
                "quarantine_seconds": self.static.quarantine_seconds,
            }
        if name == "brightdata":
            bd = self.brightdata
            return {
                "host": bd.host,
                "port": bd.port,
                "username": bd.username,
                "password": bd.password,
                "country": bd.country,
                "session_rotation": bd.session_rotation,
            }
        if name == "smartproxy":
            sp = self.smartproxy
            return {
                "username": sp.username,
                "password": sp.password,
                "endpoint": sp.endpoint,
                "port": sp.port,
                "country": sp.country,
            }
        return {}


class SessionConfig(BaseModel):
    redis_enabled: bool = True
    redis_url: str = "redis://localhost:6379/0"
    redis_pool_size: int = 20
    redis_socket_timeout: int = 5
    redis_retry_on_timeout: bool = True
    lru_maxsize: int = 1024
    crawl_cache_ttl: int = 86_400
    lead_cache_ttl: int = 604_800
    session_ttl: int = 604_800
    max_sessions_in_memory: int = 100
    memory_lru_text_maxsize: int = 128
    memory_lru_summary_maxsize: int = 1024
    conversation_history_limit: int = 50
    conversation_ttl: int = 2_592_000
    # LLM response cache
    llm_cache_enabled: bool = True
    llm_cache_lru_maxsize: int = 512
    llm_cache_ttl: int = 3_600  # 1 hour default
    # Context window (SummaryBufferWindow)
    context_max_tokens: int = 6_000
    context_max_turns: int = 40
    context_chunk_size: int = 10


class ScoringConfig(BaseModel):
    hot_threshold: float = 0.65
    warm_threshold: float = 0.35
    llm_enabled: bool = True
    max_outreach_points: int = 5
    max_concurrent_scorers: int = 8
    research_hot_leads: bool = True
    find_contacts: bool = True

    @field_validator("hot_threshold", "warm_threshold")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class OutputConfig(BaseModel):
    format: Literal["json", "csv"] = "json"
    save_to: str = "output/leads.json"
    top_leads: int = 20
    include_evidence: bool = True
    pretty_print: bool = True


class EventsConfig(BaseModel):
    console_observer: bool = True
    logging_observer: bool = True
    metrics_observer: bool = True
    webhook_enabled: bool = False
    webhook_url: str = ""
    webhook_secret: str = ""


class RateLimitSettings(BaseModel):
    rpm: int = 60  # requests per minute (0 = unlimited)


class RateLimitsConfig(BaseModel):
    serper: RateLimitSettings = Field(default_factory=lambda: RateLimitSettings(rpm=60))
    tavily: RateLimitSettings = Field(default_factory=lambda: RateLimitSettings(rpm=20))
    bing: RateLimitSettings = Field(default_factory=lambda: RateLimitSettings(rpm=60))
    github: RateLimitSettings = Field(default_factory=lambda: RateLimitSettings(rpm=30))
    producthunt: RateLimitSettings = Field(default_factory=lambda: RateLimitSettings(rpm=20))
    crunchbase: RateLimitSettings = Field(default_factory=lambda: RateLimitSettings(rpm=30))
    lever: RateLimitSettings = Field(default_factory=lambda: RateLimitSettings(rpm=60))

    def to_dict(self) -> dict[str, int]:
        return {k: v["rpm"] for k, v in self.model_dump().items()}


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    json_format: bool = False


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    rate_limits: RateLimitsConfig = Field(default_factory=RateLimitsConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH

    if not config_path.exists():
        logger.warning("Config not found at %s — using defaults.", config_path)
        return AppConfig()

    try:
        with open(config_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_path}: {exc}") from exc

    cleaned = _strip_comments(raw)
    cfg = AppConfig.model_validate(cleaned)
    logger.info("Config loaded: %s (provider=%s)", config_path, cfg.llm.provider)
    return cfg


def _strip_comments(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items() if not k.startswith("_comment")}
    if isinstance(obj, list):
        return [_strip_comments(i) for i in obj]
    return obj

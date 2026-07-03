from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Type

from common.llm.base import BaseLLM
from common.llm.response_cache import LLMResponseCache

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)

_DEFAULT_TTLS = {
    "icp_parser": 3_600,
    "lead_scorer": 86_400,
    "research": 86_400,
    "contact_finder": 86_400,
    "enricher": 3_600,
}


class CachedLLM(BaseLLM):
    """Decorator that adds two-tier response caching to any BaseLLM.

    Cache key = SHA-256(model_name + "|" + prompt).
    Cache miss → delegate to inner → store result.
    Cache hit  → deserialize + return (no LLM call).
    """

    def __init__(
        self,
        inner: BaseLLM,
        cache: LLMResponseCache,
        ttl: int = 3_600,
        on_cache_hit: Callable[[str], None] | None = None,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._ttl = ttl
        self._on_hit = on_cache_hit

    def invoke(self, prompt: str) -> str:
        return self._inner.invoke(prompt)

    def invoke_structured(self, prompt: str, schema: Type["BaseModel"]) -> "BaseModel":
        cached_dict = self._cache.get(prompt, self.model_name)
        if cached_dict is not None:
            try:
                if self._on_hit:
                    self._on_hit(self.model_name)
                return schema.model_validate(cached_dict)
            except Exception:
                pass  # corrupted entry — fall through to LLM

        result = self._inner.invoke_structured(prompt, schema)
        try:
            self._cache.set(prompt, self.model_name, result.model_dump(), self._ttl)
        except Exception:
            pass
        return result

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    @classmethod
    def for_agent(
        cls,
        inner: BaseLLM,
        cache: LLMResponseCache,
        agent_name: str,
        on_cache_hit: Callable[[str], None] | None = None,
    ) -> "CachedLLM":
        """Create a CachedLLM with agent-appropriate TTL."""
        ttl = _DEFAULT_TTLS.get(agent_name, 3_600)
        return cls(inner, cache, ttl=ttl, on_cache_hit=on_cache_hit)

    def __repr__(self) -> str:
        return f"<CachedLLM model={self.model_name!r} ttl={self._ttl}s>"

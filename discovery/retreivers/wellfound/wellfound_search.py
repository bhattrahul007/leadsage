from __future__ import annotations

import logging
from typing import ClassVar

from discovery.retreivers.base import BaseSearchProvider, SearchResult
from discovery.retreivers.registry import register_search_engine

logger = logging.getLogger(__name__)


@register_search_engine("wellfound")
class WellfoundSearchProvider(BaseSearchProvider):
    """
    Wellfound (formerly AngelList) via Serper site-restricted search.

    Reuses ``SERPER_API_KEY`` — no separate credential needed.
    Returns startup profiles from wellfound.com/company.
    """

    name: ClassVar[str] = "wellfound"
    env_key: ClassVar[str] = "SERPER_API_KEY"

    _SERPER_URL = "https://google.serper.dev/search"

    def search(self) -> list[SearchResult]:
        site_query = f"site:wellfound.com/company {self.query}"
        try:
            resp = self._request(
                "POST",
                self._SERPER_URL,
                headers={
                    "X-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                },
                json={"q": site_query, "num": self.config.max_results},
            )
            organic = resp.json().get("organic", [])
            results: list[SearchResult] = []
            for i, item in enumerate(organic):
                link = item.get("link", "")
                if "wellfound.com" not in link:
                    continue
                results.append(
                    self._build_result(
                        rank=i + 1,
                        title=item.get("title", ""),
                        href=link,
                        body=item.get("snippet", ""),
                        metadata={"source": "wellfound"},
                    )
                )
            return results[: self.config.max_results]
        except Exception as exc:
            logger.warning("[wellfound] search failed: %s", exc)
            return []

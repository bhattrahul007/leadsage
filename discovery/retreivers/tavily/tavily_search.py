from __future__ import annotations

import json

from discovery.retreivers.base import (
    BaseSearchProvider,
    SearchResult,
    SearchResultMetadata,
)
from discovery.retreivers.registry import register_search_engine


@register_search_engine("tavily")
class TavilySearch(BaseSearchProvider):
    """
    Tavily search provider.

    Extracts: rank, score, published_date, raw_content (when advanced depth).
    Supports: search_depth, topic, include_domains, exclude_domains,
    max_results, search_type (news uses topic="news").
    Note: Tavily does not support country/language filtering.
    """

    name = "tavily"
    env_key = "TAVILY_API_KEY"

    _BASE_URL = "https://api.tavily.com/search"

    def search(self) -> list[SearchResult]:
        cfg = self.config
        topic = "news" if cfg.search_type == "news" else cfg.topic
        payload: dict = {
            "api_key": self.api_key,
            "query": self.query,
            "search_depth": cfg.search_depth,
            "topic": topic,
            "max_results": cfg.max_results,
            "include_answer": False,
            "include_raw_content": cfg.search_depth == "advanced",
            "include_images": False,
        }
        if cfg.include_domains:
            payload["include_domains"] = cfg.include_domains
        if cfg.exclude_domains:
            payload["exclude_domains"] = cfg.exclude_domains

        try:
            resp = self._request(
                "POST",
                self._BASE_URL,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
            )
            data = resp.json()
        except Exception as exc:
            self.logger.error("Request failed: %s", exc)
            return []

        results: list[SearchResult] = []
        for idx, item in enumerate(data.get("results", []), start=1):
            link = item.get("url", "")
            if self._is_junk(link):
                continue

            meta = SearchResultMetadata(
                score=item.get("score", 0.0),
                published_date=item.get("published_date", ""),
                raw_content=item.get("raw_content", ""),
            )
            results.append(
                self._build_result(
                    rank=idx,
                    title=item.get("title", ""),
                    href=link,
                    body=item.get("content", ""),
                    metadata=meta,
                )
            )

        return results

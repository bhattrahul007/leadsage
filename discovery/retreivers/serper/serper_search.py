from __future__ import annotations

import json

from discovery.retreivers.base import (
    BaseSearchProvider,
    SearchResult,
    SearchResultMetadata,
)
from discovery.retreivers.registry import register_search_engine


@register_search_engine("serper")
class SerperSearch(BaseSearchProvider):
    """
    Google Serper provider — web and news search.

    Extracts: rank, published_date, image_url, site_links, attributes,
    knowledge_graph, answer_box, related_searches, total_results.

    Supports: country, language, time_range, include_domains, exclude_domains,
    pagination (page), safe_search, search_type (web/news).
    """

    name = "serper"
    env_key = "SERPER_API_KEY"

    _WEB_URL = "https://google.serper.dev/search"
    _NEWS_URL = "https://google.serper.dev/news"

    def search(self) -> list[SearchResult]:
        cfg = self.config
        url = self._NEWS_URL if cfg.search_type == "news" else self._WEB_URL

        query = self.query
        if cfg.exclude_domains:
            query += "".join(f" -site:{d}" for d in cfg.exclude_domains)
        if cfg.include_domains:
            query += " site:" + " OR site:".join(cfg.include_domains)

        payload: dict = {
            "q": query,
            "num": cfg.max_results,
            "page": cfg.page,
        }
        if cfg.country:
            payload["gl"] = cfg.country
        if cfg.language:
            payload["hl"] = cfg.language
        if cfg.time_range:
            payload["tbs"] = cfg.time_range
        if cfg.safe_search:
            payload["safe"] = "active"

        try:
            resp = self._request(
                "POST",
                url,
                headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                data=json.dumps(payload),
            )
            data = resp.json()
        except Exception as exc:
            self.logger.error("Request failed: %s", exc)
            return []

        total_str: str = data.get("searchInformation", {}).get("totalResults", "")
        answer_box: dict = data.get("answerBox", {})
        knowledge_graph: dict = data.get("knowledgeGraph", {})
        related_searches: list[str] = [
            r["query"] for r in data.get("relatedSearches", []) if "query" in r
        ]

        results: list[SearchResult] = []
        key = "news" if cfg.search_type == "news" else "organic"
        for item in data.get(key, []):
            link = item.get("link", "")
            if self._is_junk(link):
                continue

            meta = SearchResultMetadata(
                published_date=item.get("date", ""),
                image_url=item.get("imageUrl", ""),
                displayed_link=item.get("displayedLink", ""),
                attributes=item.get("attributes", {}),
                site_links=[
                    {"title": sl.get("title", ""), "href": sl.get("link", "")}
                    for sl in item.get("sitelinks", [])
                ],
                answer_box=answer_box,
                knowledge_graph=knowledge_graph,
                related_searches=related_searches,
                total_results=total_str,
            )
            results.append(
                self._build_result(
                    rank=item.get("position", len(results) + 1),
                    title=item.get("title", ""),
                    href=link,
                    body=item.get("snippet", ""),
                    metadata=meta,
                )
            )

        return results

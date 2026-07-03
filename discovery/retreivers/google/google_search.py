from __future__ import annotations

import os

from discovery.retreivers.base import (
    BaseSearchProvider,
    SearchConfig,
    SearchResult,
    SearchResultMetadata,
)
from discovery.retreivers.registry import register_search_engine


@register_search_engine("google_search")
class GoogleSearch(BaseSearchProvider):
    """
    Google Custom Search API provider.

    Requires two env vars: GOOGLE_API_KEY and GOOGLE_CX_KEY.

    Extracts: rank, displayed_link, page_map (OpenGraph, schema.org, metatags,
    hcard, etc.), total_results.
    Supports: country, language, include_domains, exclude_domains, pagination.
    """

    name = "google"
    env_key = "GOOGLE_API_KEY"
    cx_env_key = "GOOGLE_CX_KEY"

    _BASE_URL = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, query: str, config: SearchConfig | None = None) -> None:
        super().__init__(query, config)
        self.cx_key = os.getenv(self.cx_env_key)
        if not self.cx_key:
            raise OSError(
                f"[google] CX key missing. Set the {self.cx_env_key!r} environment variable."
            )

    def search(self) -> list[SearchResult]:
        cfg = self.config
        q = self.query

        if cfg.include_domains:
            site_filter = " OR ".join(f"site:{d}" for d in cfg.include_domains)
            q = f"({site_filter}) {q}"
        if cfg.exclude_domains:
            q += "".join(f" -site:{d}" for d in cfg.exclude_domains)

        start = ((cfg.page - 1) * 10) + 1

        params: dict = {
            "key": self.api_key,
            "cx": self.cx_key,
            "q": q,
            "num": min(cfg.max_results, 10),
            "start": start,
        }
        if cfg.country:
            params["gl"] = cfg.country
        if cfg.language:
            params["hl"] = cfg.language
        if cfg.safe_search:
            params["safe"] = "active"

        try:
            resp = self._request("GET", self._BASE_URL, params=params)
            data = resp.json()
        except Exception as exc:
            self.logger.error("Request failed: %s", exc)
            return []

        total_str: str = data.get("searchInformation", {}).get("formattedTotalResults", "")

        results: list[SearchResult] = []
        for idx, item in enumerate(data.get("items", []), start=1):
            link = item.get("link", "")
            if self._is_junk(link):
                continue

            meta = SearchResultMetadata(
                displayed_link=item.get("displayLink", ""),
                page_map=item.get("pagemap", {}),
                total_results=total_str,
                image_url=(item.get("pagemap", {}).get("cse_image", [{}])[0].get("src", "")),
            )
            results.append(
                self._build_result(
                    rank=idx,
                    title=item.get("title", ""),
                    href=link,
                    body=item.get("snippet", ""),
                    metadata=meta,
                )
            )
            if len(results) >= cfg.max_results:
                break

        return results

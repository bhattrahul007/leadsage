from __future__ import annotations

import urllib.parse

from discovery.retreivers.base import (
    BaseSearchProvider,
    SearchResult,
    SearchResultMetadata,
)
from discovery.retreivers.registry import register_search_engine


@register_search_engine("searchapi")
class SearchApiSearch(BaseSearchProvider):
    """
    SearchApi.io provider (Google engine).

    Extracts: rank, published_date, displayed_link, site_links, total_results.
    Supports: country, language, include_domains, exclude_domains, pagination,
    search_type (web/news).
    """

    name = "searchapi"
    env_key = "SEARCHAPI_API_KEY"

    _BASE_URL = "https://www.searchapi.io/api/v1/search"

    def search(self) -> list[SearchResult]:
        cfg = self.config
        query = self.query

        if cfg.include_domains:
            query += " site:" + " OR site:".join(cfg.include_domains)
        if cfg.exclude_domains:
            query += "".join(f" -site:{d}" for d in cfg.exclude_domains)

        engine = "google_news" if cfg.search_type == "news" else "google"
        params: dict = {
            "q": query,
            "engine": engine,
            "num": cfg.max_results,
            "start": (cfg.page - 1) * cfg.max_results,
        }
        if cfg.country:
            params["gl"] = cfg.country
        if cfg.language:
            params["hl"] = cfg.language
        if cfg.time_range:
            params["tbs"] = cfg.time_range

        url = self._BASE_URL + "?" + urllib.parse.urlencode(params)

        try:
            resp = self._request(
                "GET",
                url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            data = resp.json()
        except Exception as exc:
            self.logger.error("Request failed: %s", exc)
            return []

        total_str: str = str(data.get("search_information", {}).get("total_results", ""))

        results: list[SearchResult] = []
        for item in data.get("organic_results", []):
            link = item.get("link", "")
            if self._is_junk(link):
                continue

            meta = SearchResultMetadata(
                published_date=item.get("date", ""),
                displayed_link=item.get("displayed_link", ""),
                site_links=[
                    {"title": sl.get("title", ""), "href": sl.get("link", "")}
                    for sl in item.get("sitelinks", {}).get("list", [])
                ],
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
            if len(results) >= cfg.max_results:
                break

        return results

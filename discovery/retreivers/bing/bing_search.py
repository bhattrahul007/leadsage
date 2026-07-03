from __future__ import annotations

from discovery.retreivers.base import (
    BaseSearchProvider,
    SearchResult,
    SearchResultMetadata,
)
from discovery.retreivers.registry import register_search_engine


@register_search_engine("bing")
class BingSearch(BaseSearchProvider):
    """
    Bing Web Search API provider (v7).

    Extracts: rank, published_date (dateLastCrawled), displayed_link,
    site_links (deepLinks), total_results.
    Supports: country, language, include_domains, exclude_domains, pagination,
    search_type (web/news), safe_search.
    """

    name = "bing"
    env_key = "BING_API_KEY"

    _WEB_URL = "https://api.bing.microsoft.com/v7.0/search"
    _NEWS_URL = "https://api.bing.microsoft.com/v7.0/news/search"

    def search(self) -> list[SearchResult]:
        cfg = self.config
        url = self._NEWS_URL if cfg.search_type == "news" else self._WEB_URL

        q = self.query
        if cfg.include_domains:
            q += " site:" + " OR site:".join(cfg.include_domains)
        if cfg.exclude_domains:
            q += "".join(f" -site:{d}" for d in cfg.exclude_domains)

        params: dict = {
            "q": q,
            "count": cfg.max_results,
            "offset": (cfg.page - 1) * cfg.max_results,
            "textDecorations": False,
            "textFormat": "Raw",
        }
        if cfg.language:
            params["setLang"] = cfg.language
        if cfg.country:
            params["cc"] = cfg.country
        if cfg.safe_search:
            params["safeSearch"] = "Strict"
        if cfg.search_type == "web":
            params["responseFilter"] = "Webpages"

        try:
            resp = self._request(
                "GET",
                url,
                headers={"Ocp-Apim-Subscription-Key": self.api_key},
                params=params,
            )
            data = resp.json()
        except Exception as exc:
            self.logger.error("Request failed: %s", exc)
            return []

        is_news = cfg.search_type == "news"
        if is_news:
            items = data.get("value", [])
            total_str = ""
        else:
            web_pages = data.get("webPages", {})
            items = web_pages.get("value", [])
            total_str = str(web_pages.get("totalEstimatedMatches", ""))

        results: list[SearchResult] = []
        for idx, item in enumerate(items, start=1):
            link = item.get("url", "")
            if self._is_junk(link):
                continue

            body = item.get("snippet", "") or item.get("description", "")

            meta = SearchResultMetadata(
                published_date=item.get("dateLastCrawled", "") or item.get("datePublished", ""),
                displayed_link=item.get("displayUrl", ""),
                site_links=[
                    {"title": dl.get("name", ""), "href": dl.get("url", "")}
                    for dl in item.get("deepLinks", [])
                ],
                total_results=total_str,
                image_url=((item.get("image") or {}).get("thumbnail", {}).get("contentUrl", "")),
            )
            results.append(
                self._build_result(
                    rank=idx,
                    title=item.get("name", ""),
                    href=link,
                    body=body,
                    metadata=meta,
                )
            )

        return results

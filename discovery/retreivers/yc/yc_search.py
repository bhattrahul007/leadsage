from __future__ import annotations

import logging
import os
import time

from discovery.retreivers.base import BaseSearchProvider, SearchResult
from discovery.retreivers.registry import register_search_engine

logger = logging.getLogger(__name__)

_YC_API_URL = "https://yc-oss.github.io/api/companies/all.json"
_YC_CACHE_TTL = 3_600  # refresh the company list once per hour


@register_search_engine("yc")
class YCSearch(BaseSearchProvider):
    """
    Y Combinator company directory search.

    Fetches the public YC company list (maintained at yc-oss.github.io)
    and filters companies by industry, tags, team size, and keyword match
    against the query string.  No API key required.

    Set ``YC_API_URL`` in the environment to point at a different endpoint
    (e.g. a local mirror or cache).
    """

    name = "yc"
    env_key = "YC_API_KEY"  # not actually required — overridden below

    _company_cache: list[dict] = []
    _cache_loaded_at: float = 0.0

    def _load_api_key(self) -> str:
        return os.getenv(self.env_key, "")

    def search(self) -> list[SearchResult]:
        companies = self._get_companies()
        if not companies:
            return []

        query_lower = self.query.lower()
        tokens = {t for t in query_lower.split() if len(t) > 2}
        results: list[SearchResult] = []

        for company in companies:
            score = _score_yc_company(company, query_lower, tokens)
            if score == 0:
                continue

            url = company.get("url", "") or f"https://{company.get('slug', '')}.com"
            description = company.get("one_liner", "") or company.get("long_description", "")[:200]
            tags = company.get("tags", []) or []
            batch = company.get("batch", "")

            body_parts = [description]
            if tags:
                body_parts.append("Tags: " + ", ".join(tags))
            if batch:
                body_parts.append(f"YC {batch}")

            results.append(
                self._build_result(
                    rank=score,
                    title=company.get("name", ""),
                    href=url,
                    body=" | ".join(filter(None, body_parts)),
                    metadata={
                        "yc_batch": batch,
                        "yc_tags": tags,
                        "team_size": company.get("team_size", ""),
                        "location": company.get("location", ""),
                        "status": company.get("status", ""),
                        "is_hiring": company.get("is_hiring", False),
                    },
                )
            )
            if len(results) >= self.config.max_results:
                break

        results.sort(key=lambda r: -r["rank"])
        return results[: self.config.max_results]

    def _get_companies(self) -> list[dict]:
        now = time.monotonic()
        if YCSearch._company_cache and now - YCSearch._cache_loaded_at < _YC_CACHE_TTL:
            return YCSearch._company_cache

        api_url = os.getenv("YC_API_URL", _YC_API_URL)
        try:
            resp = self._request("GET", api_url)
            data = resp.json()
            YCSearch._company_cache = data if isinstance(data, list) else []
            YCSearch._cache_loaded_at = now
            logger.info("YC company list loaded: %d companies", len(YCSearch._company_cache))
            return YCSearch._company_cache
        except Exception as exc:
            logger.error("Failed to load YC company list: %s", exc)
            return []


def _score_yc_company(company: dict, query_lower: str, tokens: set[str]) -> int:
    score = 0
    name = (company.get("name") or "").lower()
    one_liner = (company.get("one_liner") or "").lower()
    long_desc = (company.get("long_description") or "").lower()
    tags = [t.lower() for t in (company.get("tags") or [])]
    all_text = f"{name} {one_liner} {long_desc} {' '.join(tags)}"

    for token in tokens:
        if token in name:
            score += 4
        elif token in one_liner:
            score += 2
        elif token in all_text:
            score += 1

    if company.get("is_hiring"):
        score += 1
    if company.get("status") == "Active":
        score += 1

    return score

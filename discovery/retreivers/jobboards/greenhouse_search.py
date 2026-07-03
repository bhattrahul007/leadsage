from __future__ import annotations

import logging
import os
from typing import ClassVar

from discovery.retreivers.base import BaseSearchProvider, SearchResult
from discovery.retreivers.registry import register_search_engine

logger = logging.getLogger(__name__)


@register_search_engine("greenhouse")
class GreenhouseJobsProvider(BaseSearchProvider):
    """
    Greenhouse public job board API.

    Configure via ``GREENHOUSE_COMPANY_SLUGS`` (comma-separated list),
    e.g. ``stripe,notion,linear``.

    Greenhouse's board API is public — no auth token required.
    """

    name: ClassVar[str] = "greenhouse"
    env_key: ClassVar[str] = "GREENHOUSE_COMPANY_SLUGS"

    _API_BASE = "https://boards-api.greenhouse.io/v1/boards"

    def _load_api_key(self) -> str:
        return os.getenv(self.env_key, "")

    def search(self) -> list[SearchResult]:
        slugs = [s.strip() for s in self.api_key.split(",") if s.strip()]
        if not slugs:
            logger.debug("[greenhouse] GREENHOUSE_COMPANY_SLUGS not set — skipping.")
            return []

        query_tokens = set(self.query.lower().split())
        results: list[SearchResult] = []

        for slug in slugs[:30]:
            try:
                resp = self._request("GET", f"{self._API_BASE}/{slug}/jobs?content=true")
                data = resp.json()
                jobs = data.get("jobs", [])

                relevant = [
                    j
                    for j in jobs
                    if query_tokens
                    & set((j.get("title", "") + " " + j.get("content", "")).lower().split())
                ]
                if not relevant:
                    continue

                roles = [j.get("title", "") for j in relevant[:5]]
                results.append(
                    self._build_result(
                        rank=len(results) + 1,
                        title=f"{slug} — {len(relevant)} open engineering roles",
                        href=f"https://{slug}.com",
                        body=", ".join(roles[:3]),
                        metadata={
                            "hiring_roles": roles,
                            "total_postings": len(jobs),
                            "source": "greenhouse",
                        },
                    )
                )
                if len(results) >= self.config.max_results:
                    break
            except Exception as exc:
                logger.debug("[greenhouse] %s failed: %s", slug, exc)

        return results

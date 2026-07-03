from __future__ import annotations

import logging
import os
from typing import ClassVar

from discovery.retreivers.base import BaseSearchProvider, SearchResult
from discovery.retreivers.registry import register_search_engine

logger = logging.getLogger(__name__)


@register_search_engine("lever")
class LeverJobsProvider(BaseSearchProvider):
    """
    Lever public jobs API — finds companies hiring engineers.

    Configure via env var ``LEVER_COMPANY_SLUGS`` (comma-separated list
    of company slugs, e.g. ``acme,stripe,notion``).

    No authentication is required; Lever's v0 API is public.
    """

    name: ClassVar[str] = "lever"
    env_key: ClassVar[str] = "LEVER_COMPANY_SLUGS"

    _API_BASE = "https://api.lever.co/v0/postings"

    def _load_api_key(self) -> str:
        return os.getenv(self.env_key, "")

    def search(self) -> list[SearchResult]:
        slugs = [s.strip() for s in self.api_key.split(",") if s.strip()]
        if not slugs:
            logger.debug("[lever] LEVER_COMPANY_SLUGS not set — no results.")
            return []

        query_tokens = set(self.query.lower().split())
        results: list[SearchResult] = []

        for slug in slugs[:30]:
            try:
                resp = self._request("GET", f"{self._API_BASE}/{slug}?mode=json")
                postings = resp.json() if isinstance(resp.json(), list) else []

                # Filter by query relevance
                relevant = [
                    p
                    for p in postings
                    if query_tokens
                    & set(
                        (p.get("text", "") + " " + p.get("categories", {}).get("team", ""))
                        .lower()
                        .split()
                    )
                ]
                if not relevant:
                    continue

                roles = [p.get("text", "") for p in relevant[:5]]
                results.append(
                    self._build_result(
                        rank=len(results) + 1,
                        title=f"{slug} — hiring {len(relevant)} engineering roles",
                        href=f"https://{slug}.com",
                        body=", ".join(roles[:3]),
                        metadata={"hiring_roles": roles, "total_postings": len(postings)},
                    )
                )
                if len(results) >= self.config.max_results:
                    break
            except Exception as exc:
                logger.debug("[lever] %s failed: %s", slug, exc)

        return results

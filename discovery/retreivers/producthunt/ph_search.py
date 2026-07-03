from __future__ import annotations

import logging
from typing import ClassVar

from discovery.retreivers.base import BaseSearchProvider, SearchConfig, SearchResult
from discovery.retreivers.registry import register_search_engine

logger = logging.getLogger(__name__)

_GQL_QUERY = """
query Posts($topic: String, $first: Int) {
  posts(first: $first, topic: $topic, order: VOTES) {
    edges {
      node {
        name
        tagline
        website
        votesCount
        topics { edges { node { name } } }
      }
    }
  }
}
"""


@register_search_engine("producthunt")
class ProductHuntSearchProvider(BaseSearchProvider):
    """ProductHunt GraphQL search — returns recently launched products."""

    name: ClassVar[str] = "producthunt"
    env_key: ClassVar[str] = "PRODUCTHUNT_API_KEY"

    _GQL_URL = "https://api.producthunt.com/v2/api/graphql"

    def search(self) -> list[SearchResult]:
        topic = self.query.replace(" ", "-").lower()[:50]
        try:
            resp = self._request(
                "POST",
                self._GQL_URL,
                json={
                    "query": _GQL_QUERY,
                    "variables": {"topic": topic, "first": self.config.max_results},
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            edges = resp.json().get("data", {}).get("posts", {}).get("edges", [])
            results: list[SearchResult] = []
            for i, edge in enumerate(edges):
                node = edge.get("node", {})
                website = node.get("website", "")
                if not website:
                    continue
                results.append(
                    self._build_result(
                        rank=i + 1,
                        title=node.get("name", ""),
                        href=website,
                        body=node.get("tagline", ""),
                        metadata={"votes": node.get("votesCount", 0)},
                    )
                )
            return results[: self.config.max_results]
        except Exception as exc:
            logger.warning("[producthunt] search failed: %s", exc)
            return []

from __future__ import annotations

import logging
import os

from discovery.retreivers.base import BaseSearchProvider, SearchConfig, SearchResult
from discovery.retreivers.registry import register_search_engine

logger = logging.getLogger(__name__)

_CRUNCHBASE_AUTOCOMPLETE_URL = "https://api.crunchbase.com/api/v4/autocomplete"


@register_search_engine("crunchbase")
class CrunchbaseSearch(BaseSearchProvider):
    """
    Crunchbase company search via the v4 Autocomplete API.

    Requires a Crunchbase Basic (free tier) API key.
    Set ``CRUNCHBASE_API_KEY`` in the environment.

    The free tier supports organization lookup and autocomplete.
    Profile URLs point to crunchbase.com/organization/<slug> so the main
    crawler can retrieve full pages if crawling is enabled.
    """

    name = "crunchbase"
    env_key = "CRUNCHBASE_API_KEY"

    def search(self) -> list[SearchResult]:
        try:
            resp = self._request(
                "GET",
                _CRUNCHBASE_AUTOCOMPLETE_URL,
                params={
                    "query": self.query,
                    "collection_ids": "organizations",
                    "limit": min(self.config.max_results, 25),
                    "user_key": self.api_key,
                },
            )
            data = resp.json()
        except Exception as exc:
            logger.error("Crunchbase search failed: %s", exc)
            return []

        entities = data.get("entities", [])
        results: list[SearchResult] = []

        for rank, entity in enumerate(entities, 1):
            props = entity.get("properties", {})
            slug = props.get("identifier", {}).get("permalink", "")
            name = props.get("identifier", {}).get("value", "")
            short_desc = props.get("short_description", "")
            profile_url = f"https://www.crunchbase.com/organization/{slug}" if slug else ""
            website = (
                props.get("website", {}).get("value", "")
                if isinstance(props.get("website"), dict)
                else ""
            )

            href = website or profile_url
            if not href:
                continue

            results.append(
                self._build_result(
                    rank=rank,
                    title=name,
                    href=href,
                    body=short_desc,
                    metadata={
                        "crunchbase_url": profile_url,
                        "cb_permalink": slug,
                        "location": props.get("location_identifiers", [{}])[0].get("value", "")
                        if props.get("location_identifiers")
                        else "",
                        "funding_stage": props.get("funding_stage", ""),
                        "employee_count": props.get("num_employees_enum", ""),
                    },
                )
            )
            if len(results) >= self.config.max_results:
                break

        return results

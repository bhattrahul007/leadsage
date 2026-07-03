from __future__ import annotations

import logging
import os

from discovery.retreivers.base import BaseSearchProvider, SearchConfig, SearchResult
from discovery.retreivers.registry import register_search_engine

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"


@register_search_engine("github")
class GitHubSearch(BaseSearchProvider):
    """
    GitHub Organization search provider.

    Searches GitHub for organisations that match the query, returning
    their profile, homepage URL, and description.

    Auth
    ----
    Without a token: 60 unauthenticated requests/hour.
    With ``GITHUB_TOKEN`` set: 5 000 requests/hour.

    The token is optional — the provider degrades gracefully without it.
    """

    name = "github"
    env_key = "GITHUB_TOKEN"

    def _load_api_key(self) -> str:
        return os.getenv(self.env_key, "")

    def search(self) -> list[SearchResult]:
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            resp = self._request(
                "GET",
                f"{_GITHUB_API_BASE}/search/users",
                headers=headers,
                params={
                    "q": f"{self.query} type:org",
                    "per_page": min(self.config.max_results, 30),
                    "page": self.config.page,
                    "sort": "best-match",
                },
            )
            data = resp.json()
        except Exception as exc:
            logger.error("GitHub search failed: %s", exc)
            return []

        items = data.get("items", [])
        results: list[SearchResult] = []

        for rank, item in enumerate(items, 1):
            login = item.get("login", "")
            profile_url = item.get("html_url", f"https://github.com/{login}")
            detail = self._fetch_org_detail(login, headers)
            homepage = detail.get("blog") or detail.get("html_url", profile_url)
            if homepage and not homepage.startswith("http"):
                homepage = f"https://{homepage}"

            description = detail.get("description") or detail.get("bio") or ""
            location = detail.get("location") or ""

            results.append(
                self._build_result(
                    rank=rank,
                    title=detail.get("name") or login,
                    href=homepage or profile_url,
                    body=description,
                    metadata={
                        "github_org": login,
                        "github_url": profile_url,
                        "location": location,
                        "public_repos": detail.get("public_repos", 0),
                        "followers": detail.get("followers", 0),
                        "created_at": detail.get("created_at", ""),
                    },
                )
            )
            if len(results) >= self.config.max_results:
                break

        return results

    def _fetch_org_detail(self, login: str, headers: dict) -> dict:
        try:
            resp = self._request(
                "GET",
                f"{_GITHUB_API_BASE}/orgs/{login}",
                headers=headers,
            )
            return resp.json()
        except Exception:
            return {}
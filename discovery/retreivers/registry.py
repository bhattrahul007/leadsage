from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discovery.retreivers.base import BaseSearchProvider, SearchConfig

_REGISTRY: dict[str, type[BaseSearchProvider]] = {}


def register_search_engine(provider_name: str):
    def wrapper(cls: type[BaseSearchProvider]) -> type[BaseSearchProvider]:
        _REGISTRY[provider_name] = cls
        return cls

    return wrapper


def get_provider(
    name: str,
    query: str,
    config: SearchConfig | None = None,
) -> BaseSearchProvider:
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"Unknown search provider {name!r}. Available: [{available}]")
    return _REGISTRY[name](query, config)


def list_providers() -> list[str]:
    return sorted(_REGISTRY)

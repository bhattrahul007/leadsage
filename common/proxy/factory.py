from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from common.proxy.base import BaseProxyProvider

if TYPE_CHECKING:
    from common.config import ProxyConfig

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[BaseProxyProvider]] = {}


def register_proxy_provider(name: str):
    """Class decorator to register a proxy provider under ``name``."""

    def decorator(cls: type[BaseProxyProvider]) -> type[BaseProxyProvider]:
        _REGISTRY[name] = cls
        logger.debug("Registered proxy provider: %s → %s", name, cls.__name__)
        return cls

    return decorator


class ProxyProviderFactory:
    """
    Creates ``BaseProxyProvider`` instances from ``ProxyConfig``.

    Built-in providers are auto-registered when this module is imported.
    Third-party providers can be registered with ``@register_proxy_provider``.

    Example::

        from common.config import load_config
        factory = ProxyProviderFactory()
        proxy = factory.create(load_config().proxy)
    """

    # Ensure built-ins are always registered
    @staticmethod
    def _ensure_registered() -> None:
        # Import triggers @register_proxy_provider decorators
        from common.proxy import (
            brightdata,  # noqa: F401
            smartproxy,  # noqa: F401
            static,  # noqa: F401
        )

    @classmethod
    def create(cls, proxy_config: ProxyConfig) -> BaseProxyProvider | None:
        """
        Create a ``BaseProxyProvider`` from config.

        Returns ``None`` if ``proxy_config.enabled`` is False or provider
        is ``"none"``.

        Args:
            proxy_config: The ``ProxyConfig`` section of ``AppConfig``.

        Returns:
            A ready-to-use ``BaseProxyProvider``, or ``None``.
        """
        cls._ensure_registered()

        if not proxy_config.enabled or proxy_config.provider in ("none", ""):
            logger.debug("Proxy disabled")
            return None

        name = proxy_config.provider
        if name not in _REGISTRY:
            available = ", ".join(sorted(_REGISTRY))
            raise ValueError(f"Unknown proxy provider: {name!r}. Available: [{available}]")

        provider_cls = _REGISTRY[name]
        kwargs = proxy_config.get_provider_kwargs(name)
        logger.info("Creating proxy provider: %s", name)
        return provider_cls(**kwargs)

    @classmethod
    def registered(cls) -> list[str]:
        cls._ensure_registered()
        return sorted(_REGISTRY)

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict


class ProxyDict(TypedDict, total=False):
    """Standard proxy format accepted by ``requests`` and ``httpx``."""

    http: str
    https: str
    no_proxy: str


class BaseProxyProvider(ABC):
    """
    Abstract proxy provider.

    Implementations must be thread-safe: ``get_proxy()``, ``rotate()``,
    and ``report_failure()`` will be called concurrently from multiple
    crawler worker threads.

    Attributes
    ----------
    name : str
        Unique slug for this provider, e.g. ``"brightdata"``.
    """

    name: str

    @abstractmethod
    def get_proxy(self) -> ProxyDict:
        """
        Return the current active proxy dict.

        Should be fast (no network call). The proxy is pre-fetched or
        taken from a pool.

        Returns:
            A ``ProxyDict`` ready to pass to ``requests.get(proxies=...)``.
        """
        ...

    @abstractmethod
    def rotate(self) -> ProxyDict:
        """
        Force a proxy rotation and return the new proxy.

        Called when a request fails with a proxy-related error (403, 407,
        connection reset, CAPTCHA detected, etc.).

        Returns:
            A fresh ``ProxyDict``.
        """
        ...

    @abstractmethod
    def report_failure(self, proxy: ProxyDict, error: str = "") -> None:
        """
        Report that ``proxy`` failed.

        Implementations should blacklist or deprioritise the proxy so it
        is not immediately returned by ``get_proxy()`` again.

        Args:
            proxy: The proxy that failed.
            error: Optional error description.
        """
        ...

    @abstractmethod
    def health(self) -> dict:
        """
        Return a dict with provider health metrics.

        Typical keys: ``active_proxies``, ``failed_proxies``, ``rotations``.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"

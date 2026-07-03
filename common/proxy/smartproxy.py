from __future__ import annotations

import logging
import threading

from common.proxy.base import BaseProxyProvider, ProxyDict
from common.proxy.factory import register_proxy_provider

logger = logging.getLogger(__name__)

_COUNTRY_PORTS: dict[str, int] = {
    "us": 10001,
    "gb": 10002,
    "de": 10003,
    "fr": 10004,
    "ca": 10005,
    "au": 10006,
    "in": 10007,
    "sg": 10008,
    # default (random global residential)
    "": 10000,
}


@register_proxy_provider("smartproxy")
class SmartProxy(BaseProxyProvider):
    """SmartProxy residential endpoint-based provider."""

    name = "smartproxy"

    def __init__(
        self,
        username: str,
        password: str,
        endpoint: str = "gate.smartproxy.com",
        port: int = 10000,
        country: str = "",
    ) -> None:
        self._username = username
        self._password = password
        self._endpoint = endpoint
        self._port = _COUNTRY_PORTS.get(country.lower(), port)
        self._lock = threading.Lock()
        self._rotations = 0
        self._failures = 0

    def get_proxy(self) -> ProxyDict:
        url = f"http://{self._username}:{self._password}@{self._endpoint}:{self._port}"
        return {"http": url, "https": url}

    def rotate(self) -> ProxyDict:
        """SmartProxy rotates automatically per-request; this is a no-op."""
        with self._lock:
            self._rotations += 1
        logger.debug("SmartProxy rotate called (automatic per-request rotation)")
        return self.get_proxy()

    def report_failure(self, proxy: ProxyDict, error: str = "") -> None:
        with self._lock:
            self._failures += 1
        logger.warning("SmartProxy failure #%d: %s", self._failures, error)

    def health(self) -> dict:
        with self._lock:
            return {
                "provider": "smartproxy",
                "endpoint": f"{self._endpoint}:{self._port}",
                "rotations": self._rotations,
                "failures": self._failures,
            }

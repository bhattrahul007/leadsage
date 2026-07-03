from __future__ import annotations

import logging
import random
import threading

from common.proxy.base import BaseProxyProvider, ProxyDict
from common.proxy.factory import register_proxy_provider

logger = logging.getLogger(__name__)


@register_proxy_provider("brightdata")
class BrightDataProxy(BaseProxyProvider):
    """
    BrightData residential/datacenter proxy with optional session rotation.

    Session rotation modes:
    - ``"per_request"`` — fresh session ID per rotation (different exit IP)
    - ``"sticky"``      — fixed session until you call ``rotate()``

    For country targeting, set ``country`` in config (e.g. ``"us"``, ``"gb"``).
    For city targeting, set ``city`` (e.g. ``"new_york"``).
    """

    name = "brightdata"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        country: str | None = None,
        city: str | None = None,
        session_rotation: str = "per_request",
    ) -> None:
        self._host = host
        self._port = port
        self._base_username = username
        self._password = password
        self._country = country
        self._city = city
        self._rotation_mode = session_rotation
        self._lock = threading.Lock()
        self._session_id = self._new_session_id()
        self._rotations = 0
        self._failures = 0

    def get_proxy(self) -> ProxyDict:
        url = self._build_proxy_url()
        return {"http": url, "https": url}

    def rotate(self) -> ProxyDict:
        with self._lock:
            self._rotations += 1
            self._session_id = self._new_session_id()
        logger.debug("BrightData rotated to session %s", self._session_id)
        return self.get_proxy()

    def report_failure(self, proxy: ProxyDict, error: str = "") -> None:
        with self._lock:
            self._failures += 1
        logger.warning("BrightData proxy failure #%d: %s", self._failures, error)
        # Auto-rotate on failure in per_request mode
        if self._rotation_mode == "per_request":
            self.rotate()

    def health(self) -> dict:
        with self._lock:
            return {
                "provider": "brightdata",
                "host": self._host,
                "session": self._session_id,
                "rotations": self._rotations,
                "failures": self._failures,
            }

    def _build_proxy_url(self) -> str:
        username = self._base_username
        if self._country:
            username += f"-country-{self._country}"
        if self._city:
            username += f"-city-{self._city}"
        if self._rotation_mode == "sticky":
            username += f"-session-{self._session_id}"
        return f"http://{username}:{self._password}@{self._host}:{self._port}"

    @staticmethod
    def _new_session_id() -> str:
        return hex(random.getrandbits(32))[2:]

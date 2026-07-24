"""Per-host RPS ceiling enforcement (SPEC §2.3)."""

from __future__ import annotations

import time
from urllib.parse import urlparse

from scrapy.http import Request


class RateCeilingMiddleware:
    """Enforce max_rps_per_host via download_delay when requests would exceed RPS."""

    def __init__(self, max_rps_per_host: float):
        self.max_rps_per_host = max_rps_per_host
        self.min_interval = (1.0 / max_rps_per_host) if max_rps_per_host > 0 else 0.0
        self._last_by_host: dict[str, float] = {}

    @classmethod
    def from_crawler(cls, crawler):
        rps = crawler.settings.getfloat("ARIADNE_MAX_RPS_PER_HOST", 2.0)
        return cls(rps)

    def process_request(self, request: Request):
        if self.min_interval <= 0:
            return None
        host = urlparse(request.url).netloc
        if not host:
            return None
        now = time.monotonic()
        last = self._last_by_host.get(host, 0.0)
        elapsed = now - last
        if elapsed < self.min_interval:
            delay = self.min_interval - elapsed
            existing = float(request.meta.get("download_delay", 0) or 0)
            request.meta["download_delay"] = max(existing, delay)
            self._last_by_host[host] = now + delay
        else:
            self._last_by_host[host] = now
        return None

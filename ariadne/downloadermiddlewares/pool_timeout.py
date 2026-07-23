"""Re-schedule L2 requests after BrowserPool checkout/execution timeouts (SPEC §5.2.1)."""

from __future__ import annotations

import asyncio
import logging

from scrapy.http import Request

logger = logging.getLogger(__name__)


class PoolTimeoutRequeueMiddleware:
    """High-priority requeue when L2 pool checkout or execution times out."""

    def __init__(self, crawler):
        self.crawler = crawler
        self.priority = crawler.settings.getint("ARIADNE_ESCALATION_PRIORITY", 100)
        self.max_requeues = crawler.settings.getint("ARIADNE_L2_REQUEUE_MAX", 3)
        self.backoff = crawler.settings.getfloat("ARIADNE_L2_REQUEUE_DELAY", 2.0)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_exception(self, request: Request, exception, spider):
        if not self._should_requeue(request, exception):
            return None

        count = int(request.meta.get("ariadne_l2_requeue_count", 0))
        if count >= self.max_requeues:
            logger.warning(
                "L2 pool requeue cap (%s) reached for %s — giving up",
                self.max_requeues,
                request.url,
            )
            return None

        meta = dict(request.meta)
        meta["ariadne_l2_requeue_count"] = count + 1
        meta.pop("ariadne_requeue_l2", None)
        meta.pop("ariadne_pool_timeout", None)
        meta["download_delay"] = self.backoff * (count + 1)

        self.crawler.stats.inc_value("ariadne/l2_pool_requeue")
        logger.info(
            "Re-scheduling L2 after pool timeout (attempt %s/%s): %s",
            count + 1,
            self.max_requeues,
            request.url,
        )

        return request.replace(
            meta=meta,
            dont_filter=True,
            priority=self.priority,
        )

    def _should_requeue(self, request: Request, exception) -> bool:
        mode = request.meta.get("transport_mode", "")
        if not (mode == "L2_browser" or str(mode).startswith("L2")):
            return False
        if request.meta.get("ariadne_requeue_l2") or request.meta.get("ariadne_pool_timeout"):
            return True
        if isinstance(exception, (TimeoutError, asyncio.TimeoutError)):
            msg = str(exception).lower()
            if "checkout queue timeout" in msg or "l2 execution timeout" in msg:
                return True
        return False

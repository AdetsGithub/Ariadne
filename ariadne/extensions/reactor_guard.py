"""Fail closed if AsyncioSelectorReactor is not active."""

from __future__ import annotations

import logging

from scrapy import signals
from scrapy.exceptions import NotConfigured

logger = logging.getLogger(__name__)

REQUIRED = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"


class AsyncioReactorGuard:
    def __init__(self, crawler):
        configured = crawler.settings.get("TWISTED_REACTOR")
        if configured != REQUIRED:
            raise NotConfigured(
                f"Ariadne requires TWISTED_REACTOR={REQUIRED!r}, got {configured!r}"
            )
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(crawler)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        return ext

    def spider_opened(self, spider):
        try:
            from twisted.internet import reactor

            cls_name = f"{reactor.__class__.__module__}.{reactor.__class__.__name__}"
            if "asyncioreactor" not in cls_name.lower():
                spider.logger.error(
                    "AsyncioReactorGuard: active reactor is %s — expected AsyncioSelectorReactor",
                    cls_name,
                )
            else:
                spider.logger.info("AsyncioReactorGuard: OK (%s)", cls_name)
        except Exception as exc:
            spider.logger.warning("Could not introspect reactor: %s", exc)

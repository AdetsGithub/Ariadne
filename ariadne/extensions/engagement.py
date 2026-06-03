"""Log engagement authorization banner at crawl start."""

from __future__ import annotations

import logging

from scrapy import signals

logger = logging.getLogger(__name__)


class EngagementBanner:
    def __init__(self, engagement: dict | None):
        self.engagement = engagement

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(crawler.settings.get("ARIADNE_ENGAGEMENT"))
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        return ext

    def spider_opened(self, spider):
        if not self.engagement:
            spider.logger.warning("No ARIADNE_ENGAGEMENT configured")
            return
        meta = self.engagement.get("engagement") or {}
        spider.logger.info(
            "=== Ariadne engagement %s | client=%s | operator=%s | until=%s ===",
            meta.get("id"),
            meta.get("client"),
            meta.get("operator"),
            meta.get("authorized_until"),
        )

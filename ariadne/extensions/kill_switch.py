"""Kill switch via env var / sentinel file / SIGTERM drain."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from scrapy import signals
from scrapy.exceptions import CloseSpider

logger = logging.getLogger(__name__)


class KillSwitchExtension:
    def __init__(self, crawler):
        self.crawler = crawler
        self.path = os.environ.get("ARIADNE_KILL_FILE", ".ariadne.kill")

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(crawler)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.request_scheduled, signal=signals.request_scheduled)
        return ext

    def spider_opened(self, spider):
        if os.environ.get("ARIADNE_KILL") == "1":
            raise CloseSpider("kill_switch_env")

    def request_scheduled(self, request, spider):
        if os.environ.get("ARIADNE_KILL") == "1" or Path(self.path).exists():
            self.crawler.engine.close_spider(spider, "kill_switch")

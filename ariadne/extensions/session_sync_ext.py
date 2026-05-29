"""Initialize SessionSyncService with Playwright Chromium TLS anchor when L2 enabled."""

from __future__ import annotations

import logging

from scrapy import signals

from ariadne.session import SessionSyncService, set_session_sync
from ariadne.stealth.chromium import detect_playwright_chromium_major

logger = logging.getLogger(__name__)


class SessionSyncExtension:
    def __init__(self, crawler):
        self.crawler = crawler
        profiles = crawler.settings.get("ARIADNE_IMPERSONATE_PROFILES")
        proxies = crawler.settings.get("ARIADNE_PROXY_LIST") or []
        proxy_url = crawler.settings.get("ARIADNE_PROXY_URL")
        if proxy_url:
            proxies = [proxy_url, *list(proxies)]

        l2_enabled = crawler.settings.getbool("ARIADNE_BROWSER_POOL_ENABLED", False)
        chromium_major = None
        if l2_enabled:
            chromium_major = detect_playwright_chromium_major()
            if chromium_major is None:
                logger.warning(
                    "L2 enabled but Playwright Chromium version undetectable — "
                    "falling back to catalog without TLS anchor (unsafe for handoff)"
                )
            else:
                logger.info("TLS anchor: Playwright Chromium major=%s", chromium_major)
                crawler.stats.set_value("ariadne/chromium_major", chromium_major)

        self.service = SessionSyncService(
            impersonate_profiles=profiles,
            proxy_list=list(proxies) if proxies else None,
            challenge_lease_ttl=crawler.settings.getfloat("ARIADNE_CHALLENGE_LEASE_TTL", 120),
            chromium_major=chromium_major,
            require_l2_anchor=bool(l2_enabled and chromium_major is not None),
        )

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(crawler)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_opened(self, spider):
        set_session_sync(self.service)
        spider.logger.info(
            "SessionSyncExtension: ready (profiles=%s l2_anchor=%s)",
            [p.profile_id for p in self.service._profiles],
            self.service.require_l2_anchor,
        )

    def spider_closed(self, spider):
        set_session_sync(None)

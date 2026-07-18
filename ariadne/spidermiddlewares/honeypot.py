"""Honeypot link filtering — L1 unverified links deferred by default."""

from __future__ import annotations

import logging
import re

from scrapy.http import Request, Response

logger = logging.getLogger(__name__)

HONEYPOT_CLASSES = {"hidden", "invisible", "honeypot", "trap", "sr-only"}
INLINE_HIDDEN = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0",
    re.I,
)


def is_inline_honeypot(tag_html: str) -> bool:
    if INLINE_HIDDEN.search(tag_html):
        return True
    class_m = re.search(r'class=["\']([^"\']+)["\']', tag_html, re.I)
    if class_m:
        classes = set(class_m.group(1).lower().split())
        if classes & HONEYPOT_CLASSES:
            return True
    return False


class HoneypotFilterMiddleware:
    def __init__(self, crawler, l1_unverified: str = "defer"):
        self.crawler = crawler
        self.l1_unverified = l1_unverified

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler, crawler.settings.get("ARIADNE_HONEYPOT_L1_UNVERIFIED", "defer"))

    def process_spider_output(self, response: Response, result, spider=None):
        mode = response.request.meta.get("transport_mode", "L1_impersonate") if response.request else "L1"
        for item in result:
            if isinstance(item, Request):
                if item.meta.get("honeypot_suspect") and self.l1_unverified == "defer":
                    if mode.startswith("L1") or mode.startswith("L0"):
                        item.meta["transport_mode"] = "L2_browser"
                        item.meta["honeypot_validate"] = True
                        item.meta["allow_l2_stub"] = True
                        kind = (
                            "robots Disallow"
                            if item.meta.get("from_robots_hint")
                            else "unverified link"
                        )
                        logger.debug("Deferring %s to L2 validation: %s", kind, item.url)
                yield item
            else:
                yield item

    async def process_spider_output_async(self, response: Response, result, spider=None):
        from ariadne.scrapy_compat import mirror_spider_output

        async for o in mirror_spider_output(
            self.process_spider_output, response, result, spider
        ):
            yield o

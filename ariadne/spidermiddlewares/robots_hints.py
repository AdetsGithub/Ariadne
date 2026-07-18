"""Fetch robots.txt hints and emit RobotsHintItems (observe mode default)."""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from scrapy import Request
from scrapy.http import Response

from ariadne.items import RobotsHintItem

logger = logging.getLogger(__name__)


class RobotsHintMiddleware:
    def __init__(self, crawler, respect_robots: str = "observe"):
        self.crawler = crawler
        self.respect_robots = respect_robots
        self._fetched: set[str] = set()

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler, crawler.settings.get("ARIADNE_RESPECT_ROBOTS", "observe"))

    def process_spider_output(self, response: Response, result, spider=None):
        spider = spider or self.crawler.spider
        for item in result:
            yield item

        if self.respect_robots == "ignore":
            return

        host = urlparse(response.url).hostname
        if not host or host in self._fetched:
            return
        robots_url = urljoin(f"{urlparse(response.url).scheme}://{host}", "/robots.txt")
        self._fetched.add(host)
        callback = (
            spider.parse_robots
            if spider is not None and hasattr(spider, "parse_robots")
            else self._parse_robots
        )
        yield Request(
            robots_url,
            callback=callback,
            meta={
                "ariadne_skip_scope": False,
                "transport_mode": "L1_impersonate",
                "dont_retry": True,
                "handle_httpstatus_list": [404],
            },
            dont_filter=True,
            priority=50,
        )

    async def process_spider_output_async(self, response: Response, result, spider=None):
        from ariadne.scrapy_compat import mirror_spider_output

        async for o in mirror_spider_output(
            self.process_spider_output, response, result, spider
        ):
            yield o

    def _parse_robots(self, response: Response):
        if response.status != 200:
            return
        yield from parse_robots_hints(response, respect=self.respect_robots)


def parse_robots_hints(response: Response, respect: str = "observe"):
    host = urlparse(response.url).hostname or ""
    text = response.text
    rp = RobotFileParser()
    try:
        rp.parse(text.splitlines())
    except Exception:
        logger.debug("Failed parsing robots.txt for %s", host)

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lower = stripped.lower()
        if lower.startswith("disallow:"):
            path = stripped.split(":", 1)[1].strip()
            if not path:
                continue
            decision = "skipped_obey" if respect == "obey" else "followed"
            yield RobotsHintItem(
                host=host,
                path=path,
                directive="disallow",
                crawl_decision=decision,
            )
            if respect == "observe" and path != "/" and hasattr(response, "request"):
                # Caller spiders may follow; MapSpider consumes hints.
                pass
        elif lower.startswith("allow:"):
            path = stripped.split(":", 1)[1].strip()
            if path:
                yield RobotsHintItem(
                    host=host,
                    path=path,
                    directive="allow",
                    crawl_decision="followed",
                )

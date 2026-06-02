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
    def __init__(self, respect_robots: str = "observe"):
        self.respect_robots = respect_robots
        self._fetched: set[str] = set()

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings.get("ARIADNE_RESPECT_ROBOTS", "observe"))

    def process_spider_output(self, response: Response, result, spider):
        for item in result:
            yield item

        if self.respect_robots == "ignore":
            return

        host = urlparse(response.url).hostname
        if not host or host in self._fetched:
            return
        # Schedule robots fetch once per host via spider callback if available
        robots_url = urljoin(f"{urlparse(response.url).scheme}://{host}", "/robots.txt")
        self._fetched.add(host)
        yield Request(
            robots_url,
            callback=spider.parse_robots if hasattr(spider, "parse_robots") else self._parse_robots,
            meta={
                "ariadne_skip_scope": False,
                "transport_mode": "L1_impersonate",
                "dont_retry": True,
                "handle_httpstatus_list": [404],
            },
            dont_filter=True,
            priority=50,
        )

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

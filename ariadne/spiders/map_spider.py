"""Map spider — URL discovery with robots hints."""

from __future__ import annotations

from urllib.parse import urlparse

import scrapy

from ariadne.spiders.base import ScopeSpider


class MapSpider(ScopeSpider):
    name = "map"

    def __init__(self, *args, start_urls=None, **kwargs):
        super().__init__(*args, **kwargs)
        if start_urls:
            if isinstance(start_urls, str):
                self.start_urls = [u.strip() for u in start_urls.split(",") if u.strip()]
            else:
                self.start_urls = list(start_urls)

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        eng = crawler.settings.get("ARIADNE_ENGAGEMENT") or {}
        crawl = eng.get("crawl") or {}
        if not getattr(spider, "start_urls", None):
            spider.start_urls = list(crawl.get("start_urls") or [])
        spider.allowed_domains = [
            d for d in (eng.get("scope") or {}).get("allow_domains") or []
        ]
        return spider

    def start_requests(self):
        mode = self.settings.get("ARIADNE_INITIAL_TRANSPORT", "L1_impersonate")
        for url in self.start_urls:
            yield scrapy.Request(
                url,
                callback=self.parse,
                meta={"transport_mode": mode, "depth": 0},
            )

    def parse(self, response):
        yield self.make_page_item(response, extraction={"kind": "map"})
        yield from self.iter_forms(response)

        depth = response.meta.get("depth", 0)
        max_depth = ((self._engagement().get("scope") or {}).get("max_depth") or 5)
        if depth >= max_depth:
            return

        for url, suspect in self.iter_safe_links(response):
            host = urlparse(url).hostname or ""
            if self.allowed_domains and not any(
                host == d or host.endswith("." + d) for d in self.allowed_domains
            ):
                continue
            meta = {
                "transport_mode": response.meta.get("transport_mode", "L1_impersonate"),
                "depth": depth + 1,
                "parent_url": response.url,
                "honeypot_suspect": suspect,
            }
            yield scrapy.Request(url, callback=self.parse, meta=meta)

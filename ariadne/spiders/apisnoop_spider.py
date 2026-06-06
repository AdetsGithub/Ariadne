"""ApiSnoop spider — L2 crawl with network interception (MAX_BODY_SIZE guarded)."""

from __future__ import annotations

from urllib.parse import urlparse

import scrapy

from ariadne.items import EndpointItem
from ariadne.spiders.map_spider import MapSpider


class ApiSnoopSpider(MapSpider):
    name = "apisnoop"

    custom_settings = {
        "ARIADNE_BROWSER_POOL_ENABLED": True,
        "ARIADNE_CAPTURE_NETWORK": True,
        "ARIADNE_INITIAL_TRANSPORT": "L2_browser",
    }

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url,
                callback=self.parse,
                meta={
                    "transport_mode": "L2_browser",
                    "capture_network": True,
                    "depth": 0,
                },
            )

    def parse(self, response):
        yield self.make_page_item(
            response,
            extraction={"kind": "apisnoop", "network_count": len(response.meta.get("ariadne_network_endpoints") or [])},
        )
        for ep in response.meta.get("ariadne_network_endpoints") or []:
            yield EndpointItem(
                url=ep["url"],
                method=ep.get("method"),
                source="network",
                auth_required=None,
                content_type=ep.get("content_type"),
                parameters=ep.get("parameters") or [],
            )
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
            yield scrapy.Request(
                url,
                callback=self.parse,
                meta={
                    "transport_mode": "L2_browser",
                    "capture_network": True,
                    "depth": depth + 1,
                    "parent_url": response.url,
                    "honeypot_suspect": suspect,
                },
            )

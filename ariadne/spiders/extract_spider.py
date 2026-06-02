"""Extract spider — map + simple title/heading extraction."""

from __future__ import annotations

from ariadne.spiders.map_spider import MapSpider


class ExtractSpider(MapSpider):
    name = "extract"

    def parse(self, response):
        extraction = {
            "kind": "extract",
            "h1": response.css("h1::text").getall(),
            "headings": response.css("h1::text, h2::text, h3::text").getall()[:50],
            "json_ld": response.css('script[type="application/ld+json"]::text').getall()[:5],
        }
        item = self.make_page_item(response, extraction=extraction)
        yield item
        yield from self.iter_forms(response)

        # Reuse map link discovery
        depth = response.meta.get("depth", 0)
        max_depth = ((self._engagement().get("scope") or {}).get("max_depth") or 5)
        if depth >= max_depth:
            return

        from urllib.parse import urlparse
        import scrapy

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
                    "transport_mode": response.meta.get("transport_mode", "L1_impersonate"),
                    "depth": depth + 1,
                    "parent_url": response.url,
                    "honeypot_suspect": suspect,
                },
            )

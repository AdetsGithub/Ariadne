"""ApiSnoop spider — L2 crawl with network interception + map discovery.

Uses Playwright for every page and emits EndpointItem from XHR/fetch.
Also records outbound links / sitemap seeds / failures like map when enabled.
"""

from __future__ import annotations

from urllib.parse import urlparse

from ariadne.discovery.html import discovery_settings, extract_js_path_hints, iter_get_form_actions
from ariadne.discovery.sitemaps import default_sitemap_guess
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
            yield self._request(
                url,
                depth=0,
                discovery_source="seed",
                capture_network=True,
            )
        disc = discovery_settings(self)
        if disc.get("sitemaps", True):
            seen: set[str] = set()
            for url in self.start_urls:
                p = urlparse(url)
                origin = f"{p.scheme}://{p.netloc}"
                if origin in seen:
                    continue
                seen.add(origin)
                yield self._request(
                    default_sitemap_guess(origin),
                    callback=self.parse_sitemap,
                    depth=0,
                    discovery_source="sitemap",
                    dont_filter=True,
                    transport_mode="L1_impersonate",
                )

    def _transport(self) -> str:
        return "L2_browser"

    def parse(self, response):
        if response.meta.get("ariadne_asset"):
            yield from self._parse_asset_response(response)
            return
        if not self._is_html_response(response):
            return

        endpoints = response.meta.get("ariadne_network_endpoints") or []
        item = self.make_page_item(
            response,
            extraction={
                "kind": "apisnoop",
                "network_count": len(endpoints),
            },
        )
        item["discovery_source"] = response.meta.get("discovery_source") or "link"
        yield item
        for ep in endpoints:
            yield EndpointItem(
                url=ep["url"],
                method=ep.get("method"),
                source="network",
                auth_required=None,
                content_type=ep.get("content_type"),
                parameters=ep.get("parameters") or [],
            )
        yield from self.iter_forms(response)
        yield from self._discover_from_html(response)

        disc = discovery_settings(self)
        if disc.get("form_action_seeds", True):
            for action in iter_get_form_actions(response):
                yield from self._schedule_discovered(
                    action,
                    source="form_action",
                    parent_url=response.url,
                    schedule=True,
                )
        if disc.get("js_route_hints", False):
            for hint in extract_js_path_hints(response):
                yield from self._schedule_discovered(
                    hint,
                    source="js_hint",
                    parent_url=response.url,
                    schedule=True,
                )

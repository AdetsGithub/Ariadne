"""Extract spider — map discovery + heading / JSON-LD extraction."""

from __future__ import annotations

from ariadne.discovery.html import discovery_settings, extract_js_path_hints, iter_get_form_actions
from ariadne.spiders.map_spider import MapSpider


class ExtractSpider(MapSpider):
    name = "extract"

    def parse(self, response):
        if response.meta.get("ariadne_asset"):
            yield from self._parse_asset_response(response)
            return
        if not self._is_html_response(response):
            return

        extraction = {
            "kind": "extract",
            "h1": response.css("h1::text").getall(),
            "headings": response.css("h1::text, h2::text, h3::text").getall()[:50],
            "json_ld": response.css('script[type="application/ld+json"]::text').getall()[:5],
        }
        item = self.make_page_item(response, extraction=extraction)
        item["discovery_source"] = response.meta.get("discovery_source") or "link"
        yield item
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

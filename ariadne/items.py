"""Scrapy item models for Ariadne recon and sitemap-discovery artifacts.

Page / form / robots / endpoint items are the classic recon surface. Discovery
items (Asset, Outbound, Failed, UrlCandidate) extend map mode toward a
best-effort comprehensive URL inventory — see docs/SITEMAP.md.
"""

from __future__ import annotations

from typing import Any

import scrapy


class PageItem(scrapy.Item):
    url = scrapy.Field()
    final_url = scrapy.Field()
    status = scrapy.Field()
    mode = scrapy.Field()
    depth = scrapy.Field()
    parent_url = scrapy.Field()
    session_id = scrapy.Field()
    headers_subset = scrapy.Field()
    cookies_subset = scrapy.Field()
    content_hash = scrapy.Field()
    scraped_at = scrapy.Field()
    extraction = scrapy.Field()
    title = scrapy.Field()
    defense_events = scrapy.Field()
    # Optional: sitemap | link | form_action | js_hint | …
    discovery_source = scrapy.Field()


class EndpointItem(scrapy.Item):
    url = scrapy.Field()
    method = scrapy.Field()
    source = scrapy.Field()  # html | js | network | robots
    auth_required = scrapy.Field()
    content_type = scrapy.Field()
    parameters = scrapy.Field()


class RobotsHintItem(scrapy.Item):
    host = scrapy.Field()
    path = scrapy.Field()
    directive = scrapy.Field()  # disallow | allow
    crawl_decision = scrapy.Field()  # followed | skipped_obey


class FormItem(scrapy.Item):
    page_url = scrapy.Field()
    action = scrapy.Field()
    method = scrapy.Field()
    fields = scrapy.Field()


class DefenseEventItem(scrapy.Item):
    type = scrapy.Field()
    url = scrapy.Field()
    status = scrapy.Field()
    detail = scrapy.Field()
    transport_mode = scrapy.Field()
    proxy_class = scrapy.Field()
    session_id = scrapy.Field()
    timestamp = scrapy.Field()


class AssetItem(scrapy.Item):
    """Static / binary URL inventory (images, CSS, JS, PDF, …)."""

    url = scrapy.Field()
    final_url = scrapy.Field()
    status = scrapy.Field()
    content_type = scrapy.Field()
    content_length = scrapy.Field()
    parent_url = scrapy.Field()
    source = scrapy.Field()  # img | link | script | anchor | …
    method = scrapy.Field()  # HEAD | GET | none


class OutboundLinkItem(scrapy.Item):
    """Cross-host link recorded but never fetched (scope stay-in-host)."""

    url = scrapy.Field()
    host = scrapy.Field()
    parent_url = scrapy.Field()
    link_text = scrapy.Field()


class FailedUrlItem(scrapy.Item):
    """Download or scope failure — gaps in the sitemap that were attempted or blocked."""

    url = scrapy.Field()
    parent_url = scrapy.Field()
    error_type = scrapy.Field()  # download | http | scope_ignored | max_depth
    error_detail = scrapy.Field()
    attempts = scrapy.Field()
    http_status = scrapy.Field()
    source = scrapy.Field()


class UrlCandidateItem(scrapy.Item):
    """Discovered URL not yet proven via a successful HTML fetch (sitemap / JS / form)."""

    url = scrapy.Field()
    source = scrapy.Field()  # sitemap | js_hint | form_action | robots_disallow
    parent_url = scrapy.Field()
    scheduled = scrapy.Field()  # whether a Request was enqueued


def item_to_dict(item: scrapy.Item | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    return dict(item)

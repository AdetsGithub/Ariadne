"""Scrapy / pydantic item models for Ariadne recon artifacts."""

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


def item_to_dict(item: scrapy.Item | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    return dict(item)
"""Map spider — URL discovery with sitemaps, outbound inventory, and failure accounting.

See docs/SITEMAP.md for the comprehensive inventory model.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import scrapy

from ariadne.discovery import depth_allows_follow, host_allowed, normalize_max_depth
from ariadne.discovery.html import (
    classify_link,
    discovery_settings,
    extract_js_path_hints,
    iter_anchor_links,
    iter_asset_refs,
    iter_get_form_actions,
)
from ariadne.discovery.sitemaps import (
    default_sitemap_guess,
    extract_sitemap_locs_from_robots,
    parse_sitemap_xml,
)
from ariadne.items import (
    AssetItem,
    FailedUrlItem,
    OutboundLinkItem,
    UrlCandidateItem,
)
from ariadne.spidermiddlewares.honeypot import is_inline_honeypot
from ariadne.spiders.base import ScopeSpider


class MapSpider(ScopeSpider):
    name = "map"

    # Record common error statuses as PageItems when discovery.record_http_errors.
    handle_httpstatus_list = [400, 401, 403, 404, 405, 410, 429, 500, 502, 503, 504]

    def __init__(self, *args, start_urls=None, **kwargs):
        super().__init__(*args, **kwargs)
        if start_urls:
            if isinstance(start_urls, str):
                self.start_urls = [u.strip() for u in start_urls.split(",") if u.strip()]
            else:
                self.start_urls = list(start_urls)
        self._seen_discovery: set[str] = set()
        self._sitemap_fetched: set[str] = set()

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

    def _discovery(self) -> dict:
        return discovery_settings(self)

    def _max_depth(self) -> int | None:
        eng = self._engagement()
        raw = (eng.get("scope") or {}).get("max_depth", self.settings.get("ARIADNE_MAX_DEPTH", 5))
        return normalize_max_depth(raw)

    def _transport(self) -> str:
        return self.settings.get("ARIADNE_INITIAL_TRANSPORT", "L1_impersonate")

    def _page_meta(self, *, depth: int, parent_url: str | None = None, **extra) -> dict:
        meta = {
            "transport_mode": self._transport(),
            "depth": depth,
            "parent_url": parent_url,
        }
        meta.update(extra)
        disc = self._discovery()
        if disc.get("record_http_errors", True):
            meta["handle_httpstatus_list"] = list(self.handle_httpstatus_list)
        return meta

    def _request(self, url: str, *, callback=None, depth: int = 0, parent_url=None, **meta_extra):
        dont_filter = bool(meta_extra.pop("dont_filter", False))
        meta = self._page_meta(depth=depth, parent_url=parent_url, **meta_extra)
        kwargs: dict = {
            "url": url,
            "callback": callback or self.parse,
            "meta": meta,
            "dont_filter": dont_filter,
        }
        if self._discovery().get("record_failures", True):
            kwargs["errback"] = self.on_download_error
        return scrapy.Request(**kwargs)

    def start_requests(self):
        for url in self.start_urls:
            yield self._request(url, depth=0, discovery_source="seed")
        disc = self._discovery()
        if disc.get("sitemaps", True):
            seen_origins: set[str] = set()
            for url in self.start_urls:
                p = urlparse(url)
                origin = f"{p.scheme}://{p.netloc}"
                if origin in seen_origins:
                    continue
                seen_origins.add(origin)
                sm = default_sitemap_guess(origin)
                yield self._request(
                    sm,
                    callback=self.parse_sitemap,
                    depth=0,
                    discovery_source="sitemap",
                    dont_filter=True,
                )

    def parse_robots(self, response):
        yield from super().parse_robots(response)
        disc = self._discovery()
        if not disc.get("sitemaps", True) or response.status != 200:
            return
        try:
            text = response.text
        except Exception:
            text = (response.body or b"").decode("utf-8", errors="replace")
        for loc in extract_sitemap_locs_from_robots(text):
            abs_loc = urljoin(response.url, loc)
            yield UrlCandidateItem(
                url=abs_loc,
                source="sitemap",
                parent_url=response.url,
                scheduled=True,
            )
            yield self._request(
                abs_loc,
                callback=self.parse_sitemap,
                depth=0,
                parent_url=response.url,
                discovery_source="sitemap",
                dont_filter=True,
            )

    def parse_sitemap(self, response):
        if response.url in self._sitemap_fetched:
            return
        self._sitemap_fetched.add(response.url)
        if response.status != 200:
            if self._discovery().get("record_failures", True):
                yield FailedUrlItem(
                    url=response.url,
                    parent_url=response.meta.get("parent_url"),
                    error_type="http",
                    error_detail=f"sitemap status={response.status}",
                    attempts=1,
                    http_status=response.status,
                    source="sitemap",
                )
            return
        try:
            body = response.text
        except Exception:
            body = response.body or b""
        urls, children = parse_sitemap_xml(body, base_url=response.url)
        for child in children:
            if child in self._sitemap_fetched:
                continue
            if not self._url_in_scope(child):
                yield OutboundLinkItem(
                    url=child,
                    host=urlparse(child).hostname or "",
                    parent_url=response.url,
                    link_text="sitemapindex",
                )
                continue
            yield UrlCandidateItem(
                url=child, source="sitemap", parent_url=response.url, scheduled=True
            )
            yield self._request(
                child,
                callback=self.parse_sitemap,
                depth=0,
                parent_url=response.url,
                discovery_source="sitemap",
                dont_filter=True,
            )
        for loc in urls:
            yield from self._schedule_discovered(
                loc,
                source="sitemap",
                parent_url=response.url,
                schedule=True,
            )

    def parse(self, response):
        if response.meta.get("ariadne_asset"):
            yield from self._parse_asset_response(response)
            return

        if not self._is_html_response(response):
            if self._discovery().get("include_assets", False):
                yield AssetItem(
                    url=response.request.url if response.request else response.url,
                    final_url=response.url,
                    status=response.status,
                    content_type=(response.headers.get(b"Content-Type") or b"").decode(
                        "latin-1", "ignore"
                    ),
                    content_length=(response.headers.get(b"Content-Length") or b"").decode(
                        "latin-1", "ignore"
                    )
                    or None,
                    parent_url=response.meta.get("parent_url"),
                    source=response.meta.get("discovery_source") or "unknown",
                    method=response.request.method if response.request else "GET",
                )
            return

        disc = self._discovery()
        item = self.make_page_item(response, extraction={"kind": "map"})
        item["discovery_source"] = response.meta.get("discovery_source") or "link"
        yield item
        yield from self.iter_forms(response)
        yield from self._discover_from_html(response)

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

    def _discover_from_html(self, response):
        disc = self._discovery()
        depth = response.meta.get("depth", 0)
        max_depth = self._max_depth()
        allow = list(self.allowed_domains or [])

        if disc.get("include_assets", False):
            for url, source in iter_asset_refs(response):
                yield from self._emit_or_fetch_asset(url, source=source, parent_url=response.url)

        for url, text, tag_html in iter_anchor_links(response):
            if is_inline_honeypot(tag_html):
                continue
            kind = classify_link(url, allow)
            if kind == "invalid":
                continue
            if kind == "outbound":
                if disc.get("outbound_links", True):
                    yield OutboundLinkItem(
                        url=url,
                        host=urlparse(url).hostname or "",
                        parent_url=response.url,
                        link_text=text[:200] if text else "",
                    )
                continue
            if kind == "asset":
                if disc.get("include_assets", False):
                    yield from self._emit_or_fetch_asset(
                        url, source="anchor", parent_url=response.url
                    )
                continue
            if not depth_allows_follow(depth, max_depth):
                if disc.get("record_failures", True):
                    key = f"max_depth:{url}"
                    if key not in self._seen_discovery:
                        self._seen_discovery.add(key)
                        yield FailedUrlItem(
                            url=url,
                            parent_url=response.url,
                            error_type="max_depth",
                            error_detail=f"would exceed max_depth={max_depth}",
                            attempts=0,
                            http_status=None,
                            source="link",
                        )
                continue
            suspect = (not text) and ("trap" in url or "honey" in url)
            yield self._request(
                url,
                depth=depth + 1,
                parent_url=response.url,
                honeypot_suspect=suspect,
                discovery_source="link",
            )

    def _emit_or_fetch_asset(self, url: str, *, source: str, parent_url: str):
        disc = self._discovery()
        method = (disc.get("asset_method") or "head").lower()
        key = f"asset:{url}"
        if key in self._seen_discovery:
            return
        self._seen_discovery.add(key)
        if not self._url_in_scope(url):
            if disc.get("outbound_links", True):
                yield OutboundLinkItem(
                    url=url,
                    host=urlparse(url).hostname or "",
                    parent_url=parent_url,
                    link_text=source,
                )
            return
        if method == "none":
            yield AssetItem(
                url=url,
                final_url=None,
                status=None,
                content_type=None,
                content_length=None,
                parent_url=parent_url,
                source=source,
                method="none",
            )
            return
        http_method = "HEAD" if method == "head" else "GET"
        meta = self._page_meta(
            depth=0,
            parent_url=parent_url,
            ariadne_asset=True,
            discovery_source=source,
        )
        kwargs = {
            "url": url,
            "method": http_method,
            "callback": self.parse,
            "meta": meta,
        }
        if disc.get("record_failures", True):
            kwargs["errback"] = self.on_download_error
        yield scrapy.Request(**kwargs)

    def _parse_asset_response(self, response):
        ctype = (response.headers.get(b"Content-Type") or b"").decode("latin-1", "ignore")
        clen = (response.headers.get(b"Content-Length") or b"").decode("latin-1", "ignore")
        yield AssetItem(
            url=response.request.url if response.request else response.url,
            final_url=response.url,
            status=response.status,
            content_type=ctype or None,
            content_length=clen or None,
            parent_url=response.meta.get("parent_url"),
            source=response.meta.get("discovery_source") or "asset",
            method=response.request.method if response.request else "GET",
        )

    def _schedule_discovered(self, url: str, *, source: str, parent_url: str, schedule: bool):
        disc = self._discovery()
        key = f"{source}:{url}"
        if key in self._seen_discovery:
            return
        self._seen_discovery.add(key)
        if not self._url_in_scope(url):
            if disc.get("outbound_links", True):
                yield OutboundLinkItem(
                    url=url,
                    host=urlparse(url).hostname or "",
                    parent_url=parent_url,
                    link_text=source,
                )
            yield UrlCandidateItem(
                url=url, source=source, parent_url=parent_url, scheduled=False
            )
            return
        yield UrlCandidateItem(
            url=url, source=source, parent_url=parent_url, scheduled=schedule
        )
        if schedule:
            yield self._request(
                url,
                depth=0,
                parent_url=parent_url,
                discovery_source=source,
            )

    def _url_in_scope(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        if self.allowed_domains and not host_allowed(host, list(self.allowed_domains)):
            return False
        eng = self._engagement()
        scope = eng.get("scope") or {}
        deny = [re.compile(p) for p in (scope.get("deny_url_regex") or [])]
        if deny and any(p.search(url) for p in deny):
            return False
        allow = [re.compile(p) for p in (scope.get("allow_url_regex") or [])]
        if allow and not any(p.search(url) for p in allow):
            return False
        return True

    def on_download_error(self, failure):
        if not self._discovery().get("record_failures", True):
            return
        request = failure.request
        yield FailedUrlItem(
            url=request.url,
            parent_url=request.meta.get("parent_url"),
            error_type="download",
            error_detail=(
                f"{failure.type.__name__ if failure.type else 'Error'}: {failure.value!s}"
            )[:500],
            attempts=request.meta.get("retry_times", 0) + 1,
            http_status=None,
            source=request.meta.get("discovery_source") or "link",
        )

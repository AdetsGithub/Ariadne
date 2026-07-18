"""Base spider with scope-aware helpers."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import scrapy

from ariadne.items import FormItem, PageItem
from ariadne.spidermiddlewares.honeypot import is_inline_honeypot
from ariadne.spidermiddlewares.robots_hints import parse_robots_hints


class ScopeSpider(scrapy.Spider):
    name = "scope_base"
    custom_settings: dict = {}

    def _engagement(self) -> dict:
        return self.settings.get("ARIADNE_ENGAGEMENT") or {}

    def parse_robots(self, response):
        respect = self.settings.get("ARIADNE_RESPECT_ROBOTS", "observe")
        policy = self.settings.get("ARIADNE_ROBOTS_HINT_POLICY", "defer")
        hints = list(parse_robots_hints(response, respect=respect))
        for item in hints:
            yield item
        if respect != "observe":
            return
        # inventory_only: recon artifacts only — never fetch Disallow traps
        if policy == "inventory_only":
            return
        host = urlparse(response.url).hostname
        scheme = urlparse(response.url).scheme
        delay = float(self.settings.get("ARIADNE_ROBOTS_HINT_DELAY", 5.0))
        for item in hints:
            if item.get("directive") != "disallow":
                continue
            path = item.get("path") or ""
            if not path or path == "/" or "*" in path:
                continue
            target = f"{scheme}://{host}{path}"
            meta = {
                "from_robots_hint": True,
                "depth": response.meta.get("depth", 0),
                "download_delay": delay,
                "download_slot": f"robots-hint:{host}",
            }
            # defer (default): treat like L1 unverified honeypot links
            if policy == "defer":
                meta["honeypot_suspect"] = True
            elif policy == "follow":
                pass  # organic-ish crawl; still low priority
            else:
                # unknown policy → safest
                meta["honeypot_suspect"] = True
            yield scrapy.Request(
                target,
                callback=self.parse,
                meta=meta,
                priority=10,  # well below organic / escalation
            )

    def make_page_item(self, response, extraction: dict | None = None) -> PageItem:
        body = response.body or b""
        req = response.request
        mode = None
        if req:
            mode = req.meta.get("transport_mode_used") or req.meta.get("transport_mode")
        return PageItem(
            url=req.url if req else response.url,
            final_url=response.url,
            status=response.status,
            mode=mode,
            depth=response.meta.get("depth", 0),
            parent_url=response.meta.get("parent_url"),
            session_id=response.meta.get("session_id"),
            headers_subset={
                k.decode(): v[0].decode(errors="replace")
                for k, v in list(response.headers.items())[:20]
            },
            cookies_subset=response.meta.get("ariadne_response_cookies"),
            content_hash=hashlib.sha256(body).hexdigest()[:16],
            scraped_at=datetime.now(timezone.utc).isoformat(),
            extraction=extraction or {},
            title=self._safe_title(response),
            defense_events=response.meta.get("defense_events"),
        )

    @staticmethod
    def _safe_title(response) -> str:
        try:
            return (response.css("title::text").get(default="") or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _is_html_response(response) -> bool:
        ctype = (response.headers.get(b"Content-Type") or b"").decode("latin-1", "ignore").lower()
        if "text/html" in ctype or "application/xhtml" in ctype:
            return True
        # Some hosts omit Content-Type; treat empty/unknown as HTML only if body looks like markup.
        if not ctype or "text/plain" in ctype:
            head = (response.body or b"")[:200].lstrip().lower()
            return head.startswith(b"<!doctype") or head.startswith(b"<html") or b"<title" in head
        return False

    def iter_safe_links(self, response):
        """Yield absolute links, skipping obvious inline honeypots."""
        if not self._is_html_response(response):
            return
        for a in response.css("a[href]"):
            href = a.attrib.get("href")
            if not href or href.startswith(("mailto:", "javascript:", "#")):
                continue
            tag_html = a.get()
            if is_inline_honeypot(tag_html):
                continue
            url = urljoin(response.url, href)
            text = "".join(a.css("::text").getall()).strip()
            suspect = (not text) and ("trap" in href or "honey" in href)
            yield url, suspect

    def iter_forms(self, response):
        if not self._is_html_response(response):
            return
        for form in response.css("form"):
            fields = []
            for inp in form.css("input[name], select[name], textarea[name]"):
                fields.append(
                    {
                        "name": inp.attrib.get("name"),
                        "type": inp.attrib.get("type", "text"),
                    }
                )
            yield FormItem(
                page_url=response.url,
                action=urljoin(response.url, form.attrib.get("action") or ""),
                method=(form.attrib.get("method") or "GET").upper(),
                fields=fields,
            )

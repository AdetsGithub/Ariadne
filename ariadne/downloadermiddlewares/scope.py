"""Downloader middleware: scope allow/deny enforcement."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from scrapy.exceptions import IgnoreRequest
from scrapy.http import Request

logger = logging.getLogger(__name__)


class ScopeMiddleware:
    def __init__(self, engagement: dict | None):
        self.engagement = engagement or {}
        scope = (self.engagement.get("scope") or {}) if self.engagement else {}
        self.allow_domains = set(scope.get("allow_domains") or [])
        self.allow_re = [re.compile(p) for p in (scope.get("allow_url_regex") or [])]
        self.deny_re = [re.compile(p) for p in (scope.get("deny_url_regex") or [])]
        self.max_depth = int(scope.get("max_depth") or 5)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings.get("ARIADNE_ENGAGEMENT"))

    def process_request(self, request: Request, spider):
        if request.meta.get("ariadne_skip_scope") or request.meta.get("ariadne_exit_ip_canary"):
            return None
        # If no engagement loaded, allow (unit tests / doctor).
        if not self.engagement:
            return None
        url = request.url
        host = urlparse(url).hostname or ""
        depth = request.meta.get("depth", 0)
        if depth > self.max_depth:
            raise IgnoreRequest(f"max_depth exceeded for {url}")
        if self.deny_re and any(p.search(url) for p in self.deny_re):
            raise IgnoreRequest(f"deny_url_regex matched {url}")
        if self.allow_domains and not any(
            host == d or host.endswith("." + d) for d in self.allow_domains
        ):
            raise IgnoreRequest(f"host {host} not in allow_domains")
        if self.allow_re and not any(p.search(url) for p in self.allow_re):
            raise IgnoreRequest(f"allow_url_regex did not match {url}")
        return None

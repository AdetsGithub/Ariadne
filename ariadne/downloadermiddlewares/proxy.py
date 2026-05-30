"""Generic HTTP(S) proxy attachment from settings / session sticky endpoint."""

from __future__ import annotations

import itertools
import os

from scrapy.http import Request


class ProxyMiddleware:
    def __init__(self, proxy_url: str | None, proxy_list: list[str] | None):
        env = os.environ.get("ARIADNE_PROXY_URL")
        urls = list(proxy_list or [])
        if proxy_url:
            urls.insert(0, proxy_url)
        if env:
            urls.insert(0, env)
        self._cycle = itertools.cycle(urls) if urls else None
        self._urls = urls

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            crawler.settings.get("ARIADNE_PROXY_URL"),
            crawler.settings.get("ARIADNE_PROXY_LIST"),
        )

    def process_request(self, request: Request, spider):
        if request.meta.get("proxy"):
            return None
        if self._cycle:
            request.meta["proxy"] = next(self._cycle)
        return None

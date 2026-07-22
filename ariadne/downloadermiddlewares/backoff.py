"""Retry / exponential backoff on 429/503 with Retry-After respect.

Compatible with Scrapy ≥2.13 where ``RetryMiddleware._retry`` takes
``(request, reason)`` only — the spider is read from ``self.crawler.spider``.
"""

from __future__ import annotations

import logging
import random

from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message

logger = logging.getLogger(__name__)


class BackoffMiddleware(RetryMiddleware):
    def __init__(self, settings, crawler=None):
        super().__init__(settings)
        self.crawler = crawler
        self.retry_http_codes = set(settings.getlist("RETRY_HTTP_CODES") or []) | {429, 503}

    @classmethod
    def from_crawler(cls, crawler):
        mw = cls(crawler.settings, crawler)
        # Scrapy 2.13+ RetryMiddleware._retry expects self.crawler set.
        mw.crawler = crawler
        return mw

    def process_response(self, request, response):
        if request.meta.get("dont_retry", False):
            return response
        if response.status in self.retry_http_codes:
            reason = response_status_message(response.status)
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = float(
                        retry_after.decode() if isinstance(retry_after, bytes) else retry_after
                    )
                except (TypeError, ValueError):
                    delay = None
            else:
                delay = None
            retries = request.meta.get("retry_times", 0)
            if delay is None:
                delay = (2**retries) + random.uniform(0, 1)
            request.meta["download_delay"] = delay
            logger.debug("Backoff %ss for %s (%s)", delay, request.url, reason)
            return self._retry(request, reason) or response
        return response

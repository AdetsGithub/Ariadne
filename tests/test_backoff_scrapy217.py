"""BackoffMiddleware must match Scrapy 2.13+ RetryMiddleware._retry signature."""

from unittest.mock import MagicMock

from scrapy.http import HtmlResponse, Request
from scrapy.settings import Settings

from ariadne.downloadermiddlewares.backoff import BackoffMiddleware


def test_backoff_retry_signature_scrapy_217():
    settings = Settings()
    settings.set("RETRY_ENABLED", True)
    settings.set("RETRY_TIMES", 2)
    settings.set("RETRY_HTTP_CODES", [500, 503])
    crawler = MagicMock()
    crawler.settings = settings
    crawler.spider = MagicMock(name="map")
    mw = BackoffMiddleware.from_crawler(crawler)
    req = Request("https://example.com/")
    resp = HtmlResponse(url=req.url, request=req, status=500, body=b"err")
    out = mw.process_response(req, resp)
    # Either a retry Request or the original response after give-up path —
    # must not raise TypeError on _retry arity.
    assert out is not None

"""Circuit breaker on sustained empty extractions."""

import pytest
from scrapy.exceptions import CloseSpider
from scrapy.http import HtmlResponse, Request

from ariadne.downloadermiddlewares.circuit_breaker import (
    CircuitBreakerMiddleware,
    _extraction_empty,
)
from ariadne.items import PageItem


def test_extraction_empty_detects_blank_extract():
    item = PageItem(extraction={"kind": "extract", "h1": [], "headings": []})
    assert _extraction_empty(item) is True
    item2 = PageItem(extraction={"kind": "extract", "h1": ["Hello"], "headings": ["Hello"]})
    assert _extraction_empty(item2) is False
    item3 = PageItem(extraction={"kind": "map", "links": []})
    assert _extraction_empty(item3) is False


def test_circuit_breaker_trips_on_sustained_empty():
    mw = CircuitBreakerMiddleware(window=10, empty_ratio_threshold=0.50, min_samples=4)

    class FakeSpider:
        class crawler:
            class stats:
                @staticmethod
                def set_value(k, v):
                    pass

        logger = type("L", (), {"critical": staticmethod(lambda *a, **k: None), "info": staticmethod(lambda *a, **k: None)})()

    spider = FakeSpider()
    req = Request("https://example.com")
    resp = HtmlResponse(url="https://example.com", request=req, body=b"<html></html>")

    empty_item = PageItem(extraction={"kind": "extract", "h1": [], "headings": []})

    with pytest.raises(CloseSpider) as ei:
        for _ in range(10):
            list(mw.process_spider_output(resp, [empty_item], spider))
    assert ei.value.reason == "extraction_drift"
    assert mw._tripped is True


def test_circuit_breaker_does_not_trip_below_min_samples():
    mw = CircuitBreakerMiddleware(window=50, empty_ratio_threshold=0.50, min_samples=20)

    class FakeSpider:
        class crawler:
            class stats:
                @staticmethod
                def set_value(k, v):
                    pass

        logger = type("L", (), {"critical": staticmethod(lambda *a, **k: None), "info": staticmethod(lambda *a, **k: None)})()

    spider = FakeSpider()
    req = Request("https://example.com")
    resp = HtmlResponse(url="https://example.com", request=req, body=b"<html></html>")
    empty_item = PageItem(extraction={"kind": "extract", "h1": [], "headings": []})
    for _ in range(10):
        list(mw.process_spider_output(resp, [empty_item], spider))
    assert mw._tripped is False

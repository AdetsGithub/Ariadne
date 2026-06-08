"""Circuit breaker — trip on empty extractions; L3 trip is an instant kill-switch."""

from __future__ import annotations

import logging
from collections import deque

from itemadapter import ItemAdapter
from scrapy import signals
from scrapy.exceptions import CloseSpider, IgnoreRequest

logger = logging.getLogger(__name__)

L3_MODE = "L3_unlocker"


def _extraction_empty(item) -> bool | None:
    """Return True if PageItem-like extraction is empty; None if not applicable."""
    adapter = ItemAdapter(item)
    if "extraction" not in adapter.field_names() and "extraction" not in adapter:
        if not hasattr(item, "get"):
            return None
    extraction = adapter.get("extraction")
    if extraction is None:
        return None
    if not isinstance(extraction, dict):
        return False
    kind = extraction.get("kind")
    if kind == "map":
        return False
    if kind == "extract":
        h1 = extraction.get("h1") or []
        headings = extraction.get("headings") or []
        return len(h1) == 0 and len(headings) == 0
    if not extraction:
        return True
    return False


def _is_l3_meta(meta: dict | None) -> bool:
    if not meta:
        return False
    return (
        meta.get("transport_mode_used") == L3_MODE
        or meta.get("transport_mode") == L3_MODE
        or meta.get("locked_to_mode") == L3_MODE
    )


def _is_l3_response(response) -> bool:
    req = getattr(response, "request", None)
    if not req:
        return False
    return _is_l3_meta(req.meta)


class CircuitBreakerMiddleware:
    """
    Spider MW: evaluate extractions and trip.
    Downloader MW (same singleton): on L3 trip, IgnoreRequest before unlocker hits the wire.

    Registered in both SPIDER_MIDDLEWARES and DOWNLOADER_MIDDLEWARES; from_crawler
    returns one shared instance on the crawler.
    """

    def __init__(
        self,
        window: int = 50,
        empty_ratio_threshold: float = 0.50,
        min_samples: int = 20,
        l3_window: int = 10,
        l3_empty_ratio_threshold: float = 0.40,
        l3_min_samples: int = 5,
    ):
        self.window = window
        self.empty_ratio_threshold = empty_ratio_threshold
        self.min_samples = min_samples
        self.l3_window = l3_window
        self.l3_empty_ratio_threshold = l3_empty_ratio_threshold
        self.l3_min_samples = l3_min_samples
        self._results: deque[bool] = deque(maxlen=window)
        self._l3_results: deque[bool] = deque(maxlen=l3_window)
        self._tripped = False
        self._trip_kind: str | None = None  # "std" | "l3"
        self.crawler = None

    @classmethod
    def from_crawler(cls, crawler):
        existing = getattr(crawler, "ariadne_circuit_breaker", None)
        if existing is not None:
            return existing
        mw = cls(
            window=crawler.settings.getint("ARIADNE_CIRCUIT_WINDOW", 50),
            empty_ratio_threshold=crawler.settings.getfloat(
                "ARIADNE_CIRCUIT_EMPTY_RATIO", 0.50
            ),
            min_samples=crawler.settings.getint("ARIADNE_CIRCUIT_MIN_SAMPLES", 20),
            l3_window=crawler.settings.getint("ARIADNE_CIRCUIT_L3_WINDOW", 10),
            l3_empty_ratio_threshold=crawler.settings.getfloat(
                "ARIADNE_CIRCUIT_L3_EMPTY_RATIO", 0.40
            ),
            l3_min_samples=crawler.settings.getint("ARIADNE_CIRCUIT_L3_MIN_SAMPLES", 5),
        )
        mw.crawler = crawler
        crawler.ariadne_circuit_breaker = mw
        crawler.signals.connect(mw.spider_opened, signal=signals.spider_opened)
        return mw

    def spider_opened(self, spider):
        spider.logger.info(
            "CircuitBreaker: window=%s thr=%.2f min=%s | L3 window=%s thr=%.2f min=%s "
            "(L3 trip drops in-flight via IgnoreRequest)",
            self.window,
            self.empty_ratio_threshold,
            self.min_samples,
            self.l3_window,
            self.l3_empty_ratio_threshold,
            self.l3_min_samples,
        )

    def process_request(self, request, spider):
        """Downloader path: after L3 trip, never pay for another unlocker fetch."""
        if not self._tripped or self._trip_kind != "l3":
            return None
        if _is_l3_meta(request.meta):
            if self.crawler:
                self.crawler.stats.inc_value("ariadne/circuit_breaker_l3_dropped")
            logger.warning("L3 circuit open — dropping %s before wire", request.url)
            raise IgnoreRequest("circuit_breaker_l3")
        return None

    def process_spider_output(self, response, result, spider):
        is_l3 = _is_l3_response(response)
        for item in result:
            empty = None
            if not self._tripped:
                empty = _extraction_empty(item)
                if empty is not None:
                    if is_l3:
                        self._l3_results.append(empty)
                    else:
                        self._results.append(empty)
            yield item
            if not self._tripped and empty is not None:
                self._maybe_trip(spider, l3=is_l3)

    def _maybe_trip(self, spider, *, l3: bool):
        if self._tripped:
            return
        if l3:
            results = self._l3_results
            min_samples = self.l3_min_samples
            threshold = self.l3_empty_ratio_threshold
            reason = "extraction_drift_l3"
            flag = "ariadne/circuit_breaker_l3"
            kind = "l3"
        else:
            results = self._results
            min_samples = self.min_samples
            threshold = self.empty_ratio_threshold
            reason = "extraction_drift"
            flag = "ariadne/circuit_breaker_trip"
            kind = "std"

        n = len(results)
        if n < min_samples:
            return
        empty_count = sum(1 for x in results if x)
        ratio = empty_count / n
        if ratio >= threshold:
            # Flip kill-switch BEFORE CloseSpider so concurrent downloader
            # slots still in process_request drop L3 immediately.
            self._tripped = True
            self._trip_kind = kind
            msg = (
                f"Circuit breaker TRIP ({'L3' if l3 else 'std'}): "
                f"{empty_count}/{n} empty (ratio={ratio:.2f} >= {threshold})"
            )
            spider.logger.critical(msg)
            spider.crawler.stats.set_value(flag, 1)
            if l3:
                spider.logger.critical(
                    "L3 financial kill-switch armed — further L3 requests IgnoreRequest"
                )
            raise CloseSpider(reason)

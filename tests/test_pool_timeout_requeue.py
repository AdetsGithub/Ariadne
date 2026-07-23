"""PoolTimeoutRequeueMiddleware — high-priority L2 reschedule on pool timeouts."""

from scrapy.http import Request
from scrapy.utils.test import get_crawler

from ariadne.downloadermiddlewares.pool_timeout import PoolTimeoutRequeueMiddleware


def test_pool_timeout_requeues_l2_with_priority():
    crawler = get_crawler(settings_dict={"ARIADNE_ESCALATION_PRIORITY": 100})
    mw = PoolTimeoutRequeueMiddleware.from_crawler(crawler)
    req = Request(
        "https://example.com/page",
        meta={
            "transport_mode": "L2_browser",
            "ariadne_requeue_l2": True,
            "ariadne_pool_timeout": "checkout",
        },
    )
    out = mw.process_exception(req, TimeoutError("BrowserPool checkout queue timeout after 60s"), None)
    assert isinstance(out, Request)
    assert out.priority == 100
    assert out.dont_filter is True
    assert out.meta["ariadne_l2_requeue_count"] == 1
    assert "ariadne_requeue_l2" not in out.meta
    assert out.meta.get("download_delay") == 2.0


def test_pool_timeout_respects_requeue_cap():
    crawler = get_crawler(settings_dict={"ARIADNE_L2_REQUEUE_MAX": 2})
    mw = PoolTimeoutRequeueMiddleware.from_crawler(crawler)
    req = Request(
        "https://example.com/page",
        meta={
            "transport_mode": "L2_browser",
            "ariadne_requeue_l2": True,
            "ariadne_l2_requeue_count": 2,
        },
    )
    out = mw.process_exception(req, TimeoutError("checkout"), None)
    assert out is None


def test_pool_timeout_ignores_l1():
    crawler = get_crawler()
    mw = PoolTimeoutRequeueMiddleware.from_crawler(crawler)
    req = Request(
        "https://example.com/page",
        meta={"transport_mode": "L1_impersonate", "ariadne_requeue_l2": True},
    )
    out = mw.process_exception(req, TimeoutError("checkout queue timeout"), None)
    assert out is None

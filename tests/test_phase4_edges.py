"""Transparent sticky IP rotation + L3 financial circuit breaker."""

import time

import pytest
from scrapy.exceptions import CloseSpider
from scrapy.http import HtmlResponse, Request

from ariadne.downloadermiddlewares.circuit_breaker import CircuitBreakerMiddleware
from ariadne.items import PageItem
from ariadne.session import ChallengeState, SessionSyncService


def test_transparent_ip_burn_on_fresh_rechallenge():
    svc = SessionSyncService(
        impersonate_profiles=["chrome124"],
        proxy_list=["http://p1:1", "http://p2:2"],
    )
    sess = svc.get_or_create("host:ip.test")
    svc.try_begin_challenge(sess.session_id)
    svc.release_challenge(sess.session_id, ChallengeState.SOLVED)
    assert svc.maybe_transparent_ip_from_rechallenge(sess.session_id, window_seconds=60.0)
    assert sess.transparent_ip_burns == 1
    assert sess.challenge_state == ChallengeState.IDLE


def test_transparent_ip_ignores_old_clearance():
    svc = SessionSyncService(impersonate_profiles=["chrome124"], proxy_list=["http://p1:1"])
    sess = svc.get_or_create("host:old.test")
    svc.try_begin_challenge(sess.session_id)
    svc.release_challenge(sess.session_id, ChallengeState.SOLVED)
    sess.clearance_solved_at = time.time() - 120.0
    assert not svc.maybe_transparent_ip_from_rechallenge(sess.session_id, window_seconds=60.0)


def test_transparent_ip_burn_cap():
    svc = SessionSyncService(
        impersonate_profiles=["chrome124"],
        proxy_list=["http://p1:1", "http://p2:2"],
    )
    sess = svc.get_or_create("host:cap.test")
    for _ in range(3):
        svc.try_begin_challenge(sess.session_id)
        svc.release_challenge(sess.session_id, ChallengeState.SOLVED)
        assert svc.maybe_transparent_ip_from_rechallenge(sess.session_id, max_burns=3)
    svc.try_begin_challenge(sess.session_id)
    svc.release_challenge(sess.session_id, ChallengeState.SOLVED)
    assert not svc.maybe_transparent_ip_from_rechallenge(sess.session_id, max_burns=3)
    assert sess.transparent_ip_burns == 3


def test_l3_circuit_breaker_trips_faster():
    mw = CircuitBreakerMiddleware(
        window=50,
        empty_ratio_threshold=0.50,
        min_samples=20,
        l3_window=10,
        l3_empty_ratio_threshold=0.40,
        l3_min_samples=5,
    )

    class FakeSpider:
        class crawler:
            class stats:
                @staticmethod
                def set_value(k, v):
                    pass

                @staticmethod
                def inc_value(k, v=1):
                    pass

        logger = type(
            "L",
            (),
            {
                "critical": staticmethod(lambda *a, **k: None),
                "info": staticmethod(lambda *a, **k: None),
            },
        )()

    spider = FakeSpider()
    req = Request(
        "https://example.com",
        meta={"transport_mode_used": "L3_unlocker"},
    )
    resp = HtmlResponse(url="https://example.com", request=req, body=b"<html></html>")
    empty = PageItem(extraction={"kind": "extract", "h1": [], "headings": []})

    with pytest.raises(CloseSpider) as ei:
        for _ in range(8):
            list(mw.process_spider_output(resp, [empty], spider))
    assert ei.value.reason == "extraction_drift_l3"
    assert mw._trip_kind == "l3"


def test_l3_kill_switch_ignore_request():
    from scrapy.exceptions import IgnoreRequest

    mw = CircuitBreakerMiddleware(l3_window=5, l3_empty_ratio_threshold=0.4, l3_min_samples=3)
    drops = []

    class FakeStats:
        @staticmethod
        def set_value(k, v):
            pass

        @staticmethod
        def inc_value(k, v=1):
            drops.append(k)

    class FakeCrawler:
        stats = FakeStats()

    class FakeSpider:
        crawler = FakeCrawler()
        logger = type(
            "L",
            (),
            {
                "critical": staticmethod(lambda *a, **k: None),
                "info": staticmethod(lambda *a, **k: None),
            },
        )()

    mw.crawler = FakeCrawler()
    spider = FakeSpider()
    req = Request("https://t.example/", meta={"transport_mode": "L3_unlocker"})
    resp = HtmlResponse(url=req.url, request=req, body=b"<html></html>")
    empty = PageItem(extraction={"kind": "extract", "h1": [], "headings": []})

    with pytest.raises(CloseSpider):
        for _ in range(5):
            list(mw.process_spider_output(resp, [empty], spider))

    with pytest.raises(IgnoreRequest):
        mw.process_request(
            Request("https://t.example/next", meta={"transport_mode": "L3_unlocker"}),
            spider,
        )
    # Non-L3 still allowed through process_request (scheduler close handles stop)
    assert mw.process_request(Request("https://t.example/l1", meta={"transport_mode": "L1_impersonate"}), spider) is None

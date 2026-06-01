"""ChallengeDetectMiddleware re-schedules with high priority and dont_filter."""

from scrapy.http import HtmlResponse, Request
from scrapy.utils.test import get_crawler

from ariadne.downloadermiddlewares.challenge import ChallengeDetectMiddleware
from ariadne.session import SessionSyncService, set_session_sync


def _spider(crawler):
    spider = type("DummySpider", (), {})()
    spider.crawler = crawler
    return spider


def test_challenge_reschedules_l2_with_priority():
    set_session_sync(SessionSyncService(impersonate_profiles=["chrome124"]))
    crawler = get_crawler(
        settings_dict={
            "ARIADNE_ESCALATION_PRIORITY": 100,
            "ARIADNE_CHALLENGE_LEASE_TTL": 120,
            "ARIADNE_ENGAGEMENT": {
                "crawl": {"transport": {"escalate_to": ["L2_browser"]}},
            },
        }
    )
    mw = ChallengeDetectMiddleware.from_crawler(crawler)
    req = Request(
        "https://example.com/waf",
        meta={"transport_mode": "L1_impersonate", "session_id": "host:example.com"},
    )
    body = b"<html><title>Just a moment...</title>cf-browser-verification</html>"
    resp = HtmlResponse(req.url, status=403, body=body, request=req, encoding="utf-8")

    out = mw.process_response(req, resp, _spider(crawler))
    assert isinstance(out, Request)
    assert out.meta["transport_mode"] == "L2_browser"
    assert out.dont_filter is True
    assert out.priority == 100
    set_session_sync(None)


def test_second_challenge_waits_not_second_solve():
    sync = SessionSyncService(impersonate_profiles=["chrome124"])
    set_session_sync(sync)
    sync.get_or_create("host:example.com")
    crawler = get_crawler(
        settings_dict={
            "ARIADNE_ESCALATION_PRIORITY": 100,
            "ARIADNE_ENGAGEMENT": {
                "crawl": {"transport": {"escalate_to": ["L2_browser"]}},
            },
        }
    )
    mw = ChallengeDetectMiddleware.from_crawler(crawler)
    body = b"<html><title>Just a moment...</title>cf-browser-verification</html>"
    spider = _spider(crawler)

    r1 = Request(
        "https://example.com/a",
        meta={"transport_mode": "L1_impersonate", "session_id": "host:example.com"},
    )
    r2 = Request(
        "https://example.com/b",
        meta={"transport_mode": "L1_impersonate", "session_id": "host:example.com"},
    )
    out1 = mw.process_response(
        r1, HtmlResponse(r1.url, status=403, body=body, request=r1, encoding="utf-8"), spider
    )
    out2 = mw.process_response(
        r2, HtmlResponse(r2.url, status=403, body=body, request=r2, encoding="utf-8"), spider
    )
    assert out1.meta["transport_mode"] == "L2_browser"
    assert out2.meta.get("waiting_for_clearance") is True
    assert out2.priority == 100
    set_session_sync(None)

"""Robots hint parsing and Disallow fetch policy."""

from scrapy.http import Request, TextResponse

from ariadne.spidermiddlewares.robots_hints import parse_robots_hints
from ariadne.spiders.base import ScopeSpider


def test_parse_disallow_hints():
    body = """User-agent: *
Disallow: /api/v2-staging/
Disallow: /admin/
Allow: /public/
"""
    req = Request("https://app.example.com/robots.txt")
    resp = TextResponse(
        req.url, body=body.encode(), request=req, encoding="utf-8"
    )
    items = list(parse_robots_hints(resp, respect="observe"))
    paths = {(i["directive"], i["path"], i["crawl_decision"]) for i in items}
    assert ("disallow", "/api/v2-staging/", "followed") in paths
    assert ("disallow", "/admin/", "followed") in paths
    assert ("allow", "/public/", "followed") in paths


def test_obey_marks_skipped():
    body = "User-agent: *\nDisallow: /secret/\n"
    req = Request("https://app.example.com/robots.txt")
    resp = TextResponse(req.url, body=body.encode(), request=req, encoding="utf-8")
    items = list(parse_robots_hints(resp, respect="obey"))
    assert items[0]["crawl_decision"] == "skipped_obey"


def test_inventory_only_schedules_nothing():
    class Stub(ScopeSpider):
        name = "stub"

        class settings:
            @staticmethod
            def get(k, default=None):
                return {
                    "ARIADNE_RESPECT_ROBOTS": "observe",
                    "ARIADNE_ROBOTS_HINT_POLICY": "inventory_only",
                    "ARIADNE_ROBOTS_HINT_DELAY": 5.0,
                    "ARIADNE_ENGAGEMENT": {},
                }.get(k, default)

    body = "User-agent: *\nDisallow: /wp-admin/db-backup.sql.gz\n"
    req = Request("https://app.example.com/robots.txt")
    resp = TextResponse(req.url, body=body.encode(), request=req, encoding="utf-8")
    spider = Stub()
    out = list(spider.parse_robots(resp))
    assert not any(isinstance(x, Request) for x in out)


def test_defer_marks_honeypot_suspect():
    class Stub(ScopeSpider):
        name = "stub"

        class settings:
            @staticmethod
            def get(k, default=None):
                return {
                    "ARIADNE_RESPECT_ROBOTS": "observe",
                    "ARIADNE_ROBOTS_HINT_POLICY": "defer",
                    "ARIADNE_ROBOTS_HINT_DELAY": 5.0,
                    "ARIADNE_ENGAGEMENT": {},
                }.get(k, default)

    body = "User-agent: *\nDisallow: /trap/\n"
    req = Request("https://app.example.com/robots.txt")
    resp = TextResponse(req.url, body=body.encode(), request=req, encoding="utf-8")
    spider = Stub()
    reqs = [x for x in spider.parse_robots(resp) if isinstance(x, Request)]
    assert len(reqs) == 1
    assert reqs[0].meta.get("from_robots_hint") is True
    assert reqs[0].meta.get("honeypot_suspect") is True
    assert reqs[0].priority == 10

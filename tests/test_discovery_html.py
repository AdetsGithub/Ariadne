"""Tests for HTML discovery helpers (outbound / assets / JS hints)."""

from scrapy.http import HtmlResponse, Request

from ariadne.discovery.html import (
    classify_link,
    extract_js_path_hints,
    iter_anchor_links,
    iter_asset_refs,
    iter_get_form_actions,
)


def _html(body: str, url: str = "https://app.example/") -> HtmlResponse:
    req = Request(url)
    return HtmlResponse(url=url, request=req, body=body.encode(), encoding="utf-8")


def test_classify_link():
    allow = ["app.example"]
    assert classify_link("https://app.example/a", allow) == "in_scope"
    assert classify_link("https://other.example/a", allow) == "outbound"
    assert classify_link("https://app.example/x.png", allow) == "asset"
    assert classify_link("mailto:a@b.c", allow) == "invalid"


def test_iter_outbound_and_assets():
    body = """
    <html><body>
      <a href="https://cdn.example/lib.js">cdn</a>
      <a href="/page">local</a>
      <img src="/img/a.png"/>
      <script src="https://app.example/app.js"></script>
    </body></html>
    """
    resp = _html(body)
    anchors = list(iter_anchor_links(resp))
    assert any("cdn.example" in u for u, _, _ in anchors)
    assets = list(iter_asset_refs(resp))
    assert any(u.endswith(".png") for u, _ in assets)
    assert any(u.endswith(".js") for u, _ in assets)


def test_js_path_hints_and_forms():
    body = """
    <html><body>
      <script>const r = "/spa/dashboard"; const x = "/assets/app.js";</script>
      <form method="get" action="/search"></form>
    </body></html>
    """
    resp = _html(body)
    hints = extract_js_path_hints(resp)
    assert "https://app.example/spa/dashboard" in hints
    assert all(not h.endswith(".js") for h in hints)
    actions = list(iter_get_form_actions(resp))
    assert actions == ["https://app.example/search"]

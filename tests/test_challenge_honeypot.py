"""Challenge detection and honeypot heuristics."""

from scrapy.http import HtmlResponse, Request

from ariadne.challenges import detect_challenge
from ariadne.spidermiddlewares.honeypot import is_inline_honeypot


def _resp(body: str, status: int = 403, url: str = "https://example.com/"):
    req = Request(url)
    return HtmlResponse(url, status=status, body=body.encode(), request=req, encoding="utf-8")


def test_detect_cloudflare_interstitial():
    html = "<html><title>Just a moment...</title><body>cf-browser-verification</body></html>"
    m = detect_challenge(_resp(html, 403))
    assert m is not None
    assert m.type == "cloudflare"


def test_detect_datadome():
    html = "<html>Access denied. Powered by DataDome</html>"
    m = detect_challenge(_resp(html, 403))
    assert m is not None
    assert m.type == "datadome"


def test_normal_200_not_challenge():
    html = "<html><title>Hello</title><body><h1>Welcome</h1></body></html>"
    assert detect_challenge(_resp(html, 200)) is None


def test_inline_honeypot():
    assert is_inline_honeypot('<a href="/x" style="display:none">x</a>')
    assert is_inline_honeypot('<a class="honeypot" href="/trap">x</a>')
    assert not is_inline_honeypot('<a href="/about">About</a>')

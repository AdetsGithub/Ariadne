"""OPSEC-isolated exit-IP canary builder."""

from ariadne.proxy_canary import (
    build_exit_ip_canary_request,
    is_exit_ip_canary,
    parse_exit_ip_body,
)


def test_canary_request_has_no_session_artifacts():
    req = build_exit_ip_canary_request(
        echo_url="https://echo.example/ip",
        sticky_proxy="http://user:pass@proxy:8000",
        callback=lambda r: None,
    )
    assert is_exit_ip_canary(req)
    assert req.meta["ariadne_exit_ip_canary"] is True
    assert req.meta["ariadne_cookies"] == {}
    assert req.meta.get("session_id") is None
    assert req.meta["proxy"] == "http://user:pass@proxy:8000"
    assert req.meta.get("dont_merge_cookies") is True
    assert b"Referer" not in req.headers
    assert req.headers.get("Accept") in (b"text/plain,*/*;q=0.1", "text/plain,*/*;q=0.1")


def test_parse_exit_ip_body():
    assert parse_exit_ip_body(b"203.0.113.9\n") == "203.0.113.9"
    assert parse_exit_ip_body("<html>nope</html>") is None

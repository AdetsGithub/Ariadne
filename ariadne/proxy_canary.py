"""Exit-IP canary — OPSEC-isolated sticky-proxy probe (no target session artifacts)."""

from __future__ import annotations

from scrapy.http import Request

# Bare Accept — not the engagement's browser persona Accept stack
_CANARY_HEADERS = {
    "Accept": "text/plain,*/*;q=0.1",
    "Accept-Language": "en",
    "User-Agent": "AriadneExitIPCanary/1.0",
}


def build_exit_ip_canary_request(
    *,
    echo_url: str,
    sticky_proxy: str,
    callback,
    errback=None,
) -> Request:
    """
    Build an active exit-IP probe through the sticky proxy port.

    MUST be isolated from any target Session Sync jar:
    - no target cookies
    - no origin/Referer from the engagement host
    - no persona Sec-CH-UA / target UA (generic canary UA only)
    - dedicated meta flag so SessionSync / Persona middlewares skip enrichment
    """
    if not sticky_proxy:
        raise ValueError("sticky_proxy required for exit-IP canary")
    if not echo_url:
        raise ValueError("echo_url required for exit-IP canary")

    return Request(
        echo_url,
        callback=callback,
        errback=errback,
        method="GET",
        headers=dict(_CANARY_HEADERS),
        cookies={},
        dont_filter=True,
        meta={
            "proxy": sticky_proxy,
            "transport_mode": "L1_impersonate",
            "ariadne_exit_ip_canary": True,
            "ariadne_skip_scope": True,  # echo host is not the engagement target
            "ariadne_cookies": {},
            "dont_merge_cookies": True,
            "cookiejar": None,
            # No session_id — must not pull target clearance into this request
            "impersonate": "chrome131",  # TLS only; headers stay bare via middleware skip
        },
    )


def is_exit_ip_canary(request: Request) -> bool:
    return bool(request.meta.get("ariadne_exit_ip_canary"))


def parse_exit_ip_body(body: bytes | str) -> str | None:
    """Extract a single IPv4/IPv6-ish token from a plain-text echo body."""
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = body
    token = text.strip().split()[0] if text.strip() else ""
    if not token or any(c in token for c in "<>\"'"):
        return None
    # Minimal shape check
    if "." in token or ":" in token:
        return token
    return None

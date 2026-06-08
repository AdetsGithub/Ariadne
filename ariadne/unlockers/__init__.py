"""L3 commercial unlocker adapter — generic HTTP template (no vendor SDK in MVP).

Franken-session rule: clearance from the unlocker is bound to the vendor fingerprint.
After a successful L3 fetch, Session Sync locks the session to L3_unlocker and stores
cookies only in l3_cookie_jar — never merge into the L1/L2 jar.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

from scrapy.http import Headers, HtmlResponse, Request, Response

logger = logging.getLogger(__name__)

L3_MODE = "L3_unlocker"


def unlocker_endpoint() -> str | None:
    """e.g. http://api.scraperapi.com/?api_key=KEY&url=  or Bright Data unlocker URL template."""
    return os.environ.get("ARIADNE_UNLOCKER_URL") or None


def build_unlocker_request_url(target_url: str, template: str | None = None) -> str:
    tmpl = template or unlocker_endpoint()
    if not tmpl:
        raise RuntimeError(
            "L3 unlocker requested but ARIADNE_UNLOCKER_URL is unset. "
            "Set a template ending with the target URL placeholder, e.g. "
            "http://api.example.com/?key=K&url="
        )
    if "{url}" in tmpl:
        return tmpl.replace("{url}", quote(target_url, safe=""))
    # Append target URL (common ScraperAPI-style)
    return f"{tmpl}{quote(target_url, safe='')}"


async def download_via_unlocker(request: Request, settings) -> Response:
    """Fetch target through unlocker; lock session to L3; keep cookies in l3 jar only."""
    from curl_cffi.requests import AsyncSession

    from ariadne.session import get_session_sync

    sync = get_session_sync()
    sid = request.meta.get("session_id") or sync.session_id_for_url(request.url)
    sess = sync.get_or_create(sid)

    template = settings.get("ARIADNE_UNLOCKER_URL") or unlocker_endpoint()
    unlock_url = build_unlocker_request_url(request.url, template)

    timeout = request.meta.get("download_timeout") or settings.getfloat("DOWNLOAD_TIMEOUT", 180)
    async with AsyncSession() as session:
        resp = await session.get(unlock_url, timeout=timeout, allow_redirects=True)

    # Lock BEFORE storing anything that looks like clearance
    sync.lock_to_mode(sid, L3_MODE)
    vendor_cookies = dict(resp.cookies) if resp.cookies else {}
    if vendor_cookies:
        sync.set_l3_cookies(sess, vendor_cookies)
        logger.info(
            "L3 lock engaged for %s — %d vendor cookies kept in l3_cookie_jar only",
            sid,
            len(vendor_cookies),
        )

    request.meta["transport_mode_used"] = L3_MODE
    request.meta["locked_to_mode"] = L3_MODE
    # Explicitly do NOT set ariadne_response_cookies for L1/L2 jar merge
    request.meta["ariadne_l3_cookies"] = vendor_cookies
    request.meta.pop("ariadne_response_cookies", None)

    resp_headers = Headers()
    for hk, hv in resp.headers.items():
        resp_headers.appendlist(hk, hv)

    body = resp.content or b""
    return HtmlResponse(
        url=request.url,  # logical target URL, not unlocker endpoint
        status=resp.status_code,
        headers=resp_headers,
        body=body,
        request=request,
        encoding="utf-8",
    )

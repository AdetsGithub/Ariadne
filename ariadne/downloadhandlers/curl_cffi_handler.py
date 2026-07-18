"""curl_cffi download handler — L1 TLS + HTTP/2 impersonation (Scrapy ≥2.13 async API)."""

from __future__ import annotations

import logging

from scrapy.core.downloader.handlers.http11 import HTTP11DownloadHandler
from scrapy.http import Headers, HtmlResponse, Request, Response

logger = logging.getLogger(__name__)


class CurlCffiDownloadHandler:
    """Download via curl_cffi when transport_mode is L1; else fall back to Scrapy HTTP/1.1."""

    lazy = False

    def __init__(self, crawler):
        self._crawler = crawler
        self._settings = crawler.settings
        self._fallback = HTTP11DownloadHandler.from_crawler(crawler)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    async def download_request(self, request: Request) -> Response:
        mode = request.meta.get("transport_mode") or self._settings.get(
            "ARIADNE_INITIAL_TRANSPORT", "L1_impersonate"
        )
        if mode in {"L0_http"}:
            return await self._fallback.download_request(request)
        if mode in {"L2_browser", "L3_unlocker"}:
            if mode == "L3_unlocker" or request.meta.get("locked_to_mode") == "L3_unlocker":
                return await self._download_l3(request)
            if self._settings.getbool("ARIADNE_BROWSER_POOL_ENABLED", False):
                try:
                    from ariadne.browser import get_browser_pool

                    get_browser_pool()  # raises if not ready
                    return await self._download_l2(request)
                except RuntimeError:
                    logger.warning("BrowserPool not ready; falling back for %s", request.url)
            if request.meta.get("allow_l2_stub"):
                return await self._stub_l2(request)
            logger.warning(
                "L2 requested but BrowserPool inactive; using L1 curl_cffi for %s",
                request.url,
            )
        return await self._download_l1(request)

    async def _download_l3(self, request: Request) -> Response:
        from ariadne.unlockers import download_via_unlocker

        return await download_via_unlocker(request, self._settings)

    async def _download_l2(self, request: Request) -> Response:
        from ariadne.downloadhandlers.playwright_download import download_with_playwright

        try:
            return await download_with_playwright(request, self._settings)
        except TimeoutError as exc:
            logger.warning("L2 timeout: %s — spider/middleware should re-schedule", exc)
            request.meta["ariadne_requeue_l2"] = True
            raise

    async def _download_l1(self, request: Request) -> Response:
        from curl_cffi.requests import AsyncSession

        impersonate = request.meta.get("impersonate") or "chrome131"
        flat: dict[str, str] = {}
        for k, v in request.headers.items():
            key = k.decode() if isinstance(k, bytes) else str(k)
            if isinstance(v, (list, tuple)):
                val = v[0]
            else:
                val = v
            flat[key] = val.decode() if isinstance(val, bytes) else str(val)

        proxies = None
        proxy = request.meta.get("proxy")
        if proxy:
            proxies = {"http": proxy, "https": proxy}

        cookies = request.meta.get("ariadne_cookies") or {}
        timeout = request.meta.get("download_timeout") or self._settings.getfloat(
            "DOWNLOAD_TIMEOUT", 180
        )

        async with AsyncSession() as session:
            resp = await session.request(
                request.method,
                request.url,
                headers=flat or None,
                data=request.body or None,
                proxies=proxies,
                cookies=cookies,
                impersonate=impersonate,
                timeout=timeout,
                allow_redirects=True,
            )

        resp_headers = Headers()
        for hk, hv in resp.headers.items():
            # curl_cffi already decompresses; leaving Content-Encoding makes Scrapy's
            # HttpCompressionMiddleware try (and fail) to decode again.
            if str(hk).lower() in {"content-encoding", "content-length"}:
                continue
            resp_headers.appendlist(hk, hv)

        request.meta["ariadne_response_cookies"] = dict(resp.cookies) if resp.cookies else {}
        request.meta["transport_mode_used"] = "L1_impersonate"
        request.meta["impersonate_used"] = impersonate

        body = resp.content or b""
        ctype = (resp.headers.get("content-type") or "").lower()
        is_html = "text/html" in ctype or body.lstrip()[:15].lower().startswith(
            (b"<!doctype", b"<html")
        )
        is_text = is_html or any(
            t in ctype
            for t in (
                "text/",
                "application/json",
                "application/javascript",
                "application/xml",
                "+json",
                "+xml",
            )
        )
        if is_html:
            return HtmlResponse(
                url=str(resp.url),
                status=resp.status_code,
                headers=resp_headers,
                body=body,
                request=request,
                encoding="utf-8",
            )
        if is_text:
            from scrapy.http import TextResponse

            return TextResponse(
                url=str(resp.url),
                status=resp.status_code,
                headers=resp_headers,
                body=body,
                request=request,
                encoding="utf-8",
            )
        return Response(
            url=str(resp.url),
            status=resp.status_code,
            headers=resp_headers,
            body=body,
            request=request,
        )

    async def _stub_l2(self, request: Request) -> Response:
        """Test stub simulating an L2 solve that sets clearance cookies."""
        request.meta["transport_mode_used"] = "L2_browser"
        request.meta["ariadne_response_cookies"] = {"cf_clearance": "stub-clearance-token"}
        return HtmlResponse(
            url=request.url,
            status=200,
            body=b"<html><title>cleared</title><body>ok</body></html>",
            request=request,
            encoding="utf-8",
        )

    async def close(self):
        close = getattr(self._fallback, "close", None)
        if close is None:
            return
        result = close()
        if hasattr(result, "__await__"):
            await result

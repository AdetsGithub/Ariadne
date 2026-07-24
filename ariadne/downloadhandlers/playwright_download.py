"""L2 Playwright download — checkout from BrowserPool with execution_timeout."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

from scrapy.http import Headers, HtmlResponse, Request, Response

from ariadne.browser import get_browser_pool
from ariadne.browser.har import build_har_path, har_capture_enabled
from ariadne.browser.network import DEFAULT_MAX_BODY_SIZE, attach_network_sniffer, endpoints_from_bucket
from ariadne.session import ChallengeState, get_session_sync

logger = logging.getLogger(__name__)


async def download_with_playwright(request: Request, settings) -> Response:
    pool = get_browser_pool()
    sync = get_session_sync()
    sid = request.meta.get("session_id") or sync.session_id_for_url(request.url)
    sess = sync.get_or_create(sid)

    persona = dict(request.meta.get("ariadne_persona") or sess.persona.to_dict())
    persona["_cookie_url"] = request.url
    proxy = request.meta.get("proxy") or sess.proxy_endpoint
    cookies = request.meta.get("ariadne_cookies") or sync.get_cookies(sess)
    storage = sync.get_storage_state(sess)
    capture = bool(request.meta.get("capture_network") or settings.getbool("ARIADNE_CAPTURE_NETWORK", False))
    max_body = settings.getint("ARIADNE_MAX_BODY_SIZE", DEFAULT_MAX_BODY_SIZE)
    exec_timeout = settings.getfloat("ARIADNE_BROWSER_EXECUTION_TIMEOUT", pool.execution_timeout)

    network_bucket: list[dict[str, Any]] = []
    har_path: str | None = None
    if har_capture_enabled(settings):
        out_dir = settings.get("ARIADNE_OUTPUT_DIR", "artifacts")
        har_path = str(build_har_path(out_dir, sid, request.url))

    async def _run() -> Response:
        async with pool.checkout(
            sid,
            persona=persona,
            proxy=proxy,
            storage_state=storage,
            cookies=cookies if not storage else None,
            record_har_path=har_path,
        ) as context:
            # Prefer storage_state; else add cookies with correct domain
            if cookies and not storage:
                host = urlparse(request.url).hostname or ""
                await context.add_cookies(
                    [
                        {"name": n, "value": str(v), "domain": host, "path": "/"}
                        for n, v in cookies.items()
                    ]
                )

            page = await context.new_page()
            if capture:
                await attach_network_sniffer(page, bucket=network_bucket, max_body_size=max_body)

            wait_until = request.meta.get("playwright_wait_until", "domcontentloaded")
            resp = await page.goto(request.url, wait_until=wait_until, timeout=int(exec_timeout * 1000))
            # Optional CAPTCHA solve + target-specific injection (Phase 3)
            captcha_cfg = request.meta.get("captcha") or settings.get("ARIADNE_CAPTCHA")
            if captcha_cfg:
                from ariadne.captcha import InjectionConfig, solve_and_inject

                inj = captcha_cfg.get("injection") or {}
                await solve_and_inject(
                    page,
                    site_key=captcha_cfg["site_key"],
                    page_url=request.url,
                    challenge_type=captcha_cfg.get("challenge_type", "unknown"),
                    injection=InjectionConfig(
                        kind=inj.get("kind", "form"),
                        token_field_selector=inj.get(
                            "token_field_selector",
                            'textarea[name="g-recaptcha-response"], input[name="cf-turnstile-response"]',
                        ),
                        form_selector=inj.get("form_selector", "form"),
                        callback_name=inj.get("callback_name"),
                        click_selector=inj.get("click_selector"),
                    ),
                    provider=captcha_cfg.get("provider")
                    or settings.get("ARIADNE_CAPTCHA_PROVIDER")
                    or "stub",
                )
                await page.wait_for_timeout(500)
            # Light humanize scroll
            if settings.getbool("ARIADNE_BROWSER_HUMANIZE", True):
                try:
                    await page.mouse.move(100, 100)
                    await page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight*0.3))")
                    await asyncio.sleep(0.3)
                except Exception:
                    pass

            content = await page.content()
            status = resp.status if resp else 200
            final_url = page.url
            pw_cookies = await context.cookies()
            cookie_map = {c["name"]: c["value"] for c in pw_cookies}
            try:
                state = await context.storage_state()
            except Exception:
                state = None

            request.meta["ariadne_response_cookies"] = cookie_map
            request.meta["transport_mode_used"] = "L2_browser"
            if har_path:
                request.meta["har_path"] = har_path
            if state:
                sync.set_storage_state(sess, state)
            if cookie_map:
                sync.set_cookies(sess, cookie_map)

            # Challenge solved heuristic
            from ariadne.challenges import detect_challenge

            html_resp = HtmlResponse(
                url=final_url,
                status=status,
                headers=Headers({"Content-Type": ["text/html; charset=utf-8"]}),
                body=content.encode("utf-8"),
                request=request,
                encoding="utf-8",
            )
            if detect_challenge(html_resp) is None and status == 200:
                if sess.challenge_state == ChallengeState.SOLVING:
                    sync.release_challenge(sid, ChallengeState.SOLVED)
            elif sess.challenge_state == ChallengeState.SOLVING:
                sync.release_challenge(sid, ChallengeState.FAILED)

            if capture:
                request.meta["ariadne_network_endpoints"] = endpoints_from_bucket(network_bucket)

            # Conditional screenshot on challenge/error
            capture_shots = settings.get("ARIADNE_SCREENSHOT_MODE", "on_challenge_or_error")
            if capture_shots == "always" or (
                capture_shots == "on_challenge_or_error"
                and (status >= 400 or detect_challenge(html_resp))
            ):
                out_dir = settings.get("ARIADNE_OUTPUT_DIR", "artifacts")
                from pathlib import Path

                shot_dir = Path(out_dir) / "screenshots"
                shot_dir.mkdir(parents=True, exist_ok=True)
                path = shot_dir / f"{sid.replace(':', '_')}_{status}.png"
                await page.screenshot(path=str(path), full_page=False)
                request.meta["screenshot_path"] = str(path)

            await page.close()
            return html_resp

    try:
        return await asyncio.wait_for(_run(), timeout=exec_timeout)
    except TimeoutError as exc:
        msg = str(exc).lower()
        if "checkout queue timeout" in msg:
            request.meta["ariadne_pool_timeout"] = "checkout"
        else:
            request.meta.setdefault("ariadne_pool_timeout", "execution")
        request.meta["ariadne_requeue_l2"] = True
        if sess.challenge_state == ChallengeState.SOLVING:
            sync.release_challenge(sid, ChallengeState.FAILED)
        raise
    except asyncio.TimeoutError:
        if sess.challenge_state == ChallengeState.SOLVING:
            sync.release_challenge(sid, ChallengeState.FAILED)
        request.meta["ariadne_pool_timeout"] = "execution"
        request.meta["ariadne_requeue_l2"] = True
        raise TimeoutError(f"L2 execution timeout after {exec_timeout}s for {request.url}") from None

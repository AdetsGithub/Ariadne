"""Playwright Browser Pool — long-lived contexts with queue vs execution timeouts.

Queue timeout: how long a Scrapy request may wait to *acquire* a context.
Execution timeout: how long a checked-out context may run (CAPTCHA solves need 45–180s).

These MUST be separate — applying the queue timeout to the whole L2 task kills solvers
mid-flight and causes re-schedule storms.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""


@dataclass
class PooledContext:
    browser_id: str
    context: Any
    session_id: str | None = None
    pages_served: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class BrowserProcess:
    browser_id: str
    browser: Any
    contexts_served: int = 0
    draining: bool = False


class BrowserPool:
    def __init__(
        self,
        *,
        pool_size: int = 4,
        checkout_timeout: float = 60.0,
        execution_timeout: float = 180.0,
        max_contexts_served: int = 5000,
        headless: bool = False,
        disable_webrtc: bool = True,
        proxy_dns: bool = True,
    ) -> None:
        self.pool_size = pool_size
        self.checkout_timeout = checkout_timeout
        self.execution_timeout = execution_timeout
        self.max_contexts_served = max_contexts_served
        self.headless = headless
        self.disable_webrtc = disable_webrtc
        self.proxy_dns = proxy_dns

        self._playwright = None
        self._browsers: list[BrowserProcess] = []
        self._semaphore: asyncio.Semaphore | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._active: dict[str, PooledContext] = {}

    @property
    def available(self) -> bool:
        return self._playwright is not None and not self._closed

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._semaphore = asyncio.Semaphore(self.pool_size)
        await self._spawn_browser()
        logger.info(
            "BrowserPool started (pool_size=%s checkout_timeout=%ss execution_timeout=%ss headless=%s)",
            self.pool_size,
            self.checkout_timeout,
            self.execution_timeout,
            self.headless,
        )

    def _launch_args(self) -> list[str]:
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--no-first-run",
        ]
        if self.disable_webrtc:
            args.extend(
                [
                    "--disable-webrtc",
                    "--enforce-webrtc-ip-permission-check",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                ]
            )
        return args

    async def _spawn_browser(self) -> BrowserProcess:
        assert self._playwright is not None
        browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=self._launch_args(),
        )
        bp = BrowserProcess(browser_id=f"b{len(self._browsers)}-{int(time.time())}", browser=browser)
        self._browsers.append(bp)
        logger.info("Spawned Chromium process %s (version=%s)", bp.browser_id, browser.version)
        return bp

    async def _active_browser(self) -> BrowserProcess:
        async with self._lock:
            live = [b for b in self._browsers if not b.draining]
            if not live:
                return await self._spawn_browser()
            bp = live[-1]
            if bp.contexts_served >= self.max_contexts_served:
                bp.draining = True
                logger.warning(
                    "Browser %s hit max_contexts_served=%s — spawning replacement",
                    bp.browser_id,
                    self.max_contexts_served,
                )
                new_bp = await self._spawn_browser()
                # Drain old in background when idle
                asyncio.create_task(self._drain_browser(bp))
                return new_bp
            return bp

    async def _drain_browser(self, bp: BrowserProcess) -> None:
        # Wait until no active contexts reference this browser
        while any(c.browser_id == bp.browser_id for c in self._active.values()):
            await asyncio.sleep(1.0)
        try:
            await bp.browser.close()
            logger.info("Drained and closed Chromium process %s", bp.browser_id)
        except Exception as exc:
            logger.warning("Error closing browser %s: %s", bp.browser_id, exc)
        async with self._lock:
            self._browsers = [b for b in self._browsers if b.browser_id != bp.browser_id]

    @asynccontextmanager
    async def checkout(
        self,
        session_id: str,
        *,
        persona: dict[str, Any],
        proxy: str | None = None,
        storage_state: dict[str, Any] | None = None,
        cookies: dict[str, str] | None = None,
        record_har_path: str | None = None,
    ) -> AsyncIterator[Any]:
        """Acquire a context (queue timeout) then yield it (caller bound by execution_timeout)."""
        if self._semaphore is None or self._closed:
            raise RuntimeError("BrowserPool not started")

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.checkout_timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"BrowserPool checkout queue timeout after {self.checkout_timeout}s "
                f"(pool_size={self.pool_size}; CAPTCHA solves hold slots up to execution_timeout="
                f"{self.execution_timeout}s)"
            ) from exc

        ctx_wrap: PooledContext | None = None
        try:
            bp = await self._active_browser()
            viewport = persona.get("viewport") or {"width": 1920, "height": 1080}
            context_kwargs: dict[str, Any] = {
                "user_agent": persona.get("user_agent"),
                "viewport": viewport,
                "locale": persona.get("locale", "en-US"),
                "timezone_id": persona.get("timezone_id", "America/New_York"),
                "java_script_enabled": True,
            }
            if storage_state:
                context_kwargs["storage_state"] = storage_state
            if proxy:
                # Playwright proxy; DNS via proxy depends on proxy type (socks5h preferred).
                context_kwargs["proxy"] = {"server": proxy}
            if record_har_path:
                context_kwargs["record_har_path"] = record_har_path
                context_kwargs["record_har_mode"] = "minimal"
                context_kwargs["record_har_content"] = "omit"

            context = await bp.browser.new_context(**context_kwargs)
            await context.add_init_script(STEALTH_INIT_SCRIPT)
            if cookies:
                await self._apply_cookies(context, cookies, persona)

            bp.contexts_served += 1
            ctx_wrap = PooledContext(browser_id=bp.browser_id, context=context, session_id=session_id)
            self._active[session_id + str(id(context))] = ctx_wrap
            yield context
        finally:
            if ctx_wrap is not None:
                key = session_id + str(id(ctx_wrap.context))
                self._active.pop(key, None)
                try:
                    await ctx_wrap.context.close()
                except Exception as exc:
                    logger.debug("context close: %s", exc)
            self._semaphore.release()

    async def _apply_cookies(self, context: Any, cookies: dict[str, str], persona: dict) -> None:
        # Cookies need domain — callers should prefer storage_state. Best-effort for flat jar.
        pw_cookies = []
        for name, value in cookies.items():
            pw_cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": ".example.com",  # overwritten by caller storage_state when available
                    "path": "/",
                }
            )
        # Skip naive apply without domain — storage_state is the real path
        if persona.get("_cookie_url"):
            from urllib.parse import urlparse

            host = urlparse(persona["_cookie_url"]).hostname or ""
            fixed = []
            for name, value in cookies.items():
                fixed.append(
                    {
                        "name": name,
                        "value": str(value),
                        "domain": host,
                        "path": "/",
                    }
                )
            if fixed:
                await context.add_cookies(fixed)

    async def close(self) -> None:
        """Graceful teardown — MUST run before asyncio reactor finalizes (no zombie Chromium)."""
        self._closed = True
        async with self._lock:
            browsers = list(self._browsers)
            self._browsers.clear()
        for bp in browsers:
            try:
                await bp.browser.close()
            except Exception as exc:
                logger.warning("browser close error: %s", exc)
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:
                logger.warning("playwright stop error: %s", exc)
            self._playwright = None
        logger.info("BrowserPool closed")


_POOL: BrowserPool | None = None


def get_browser_pool() -> BrowserPool:
    if _POOL is None:
        raise RuntimeError("BrowserPool not initialized (is BrowserPoolExtension enabled?)")
    return _POOL


def set_browser_pool(pool: BrowserPool | None) -> None:
    global _POOL
    _POOL = pool

"""BrowserPool Scrapy extension — start/stop with zombie-Chromium-safe teardown."""

from __future__ import annotations

import asyncio
import atexit
import logging
import signal

from scrapy import signals
from scrapy.exceptions import NotConfigured
from scrapy.utils.defer import deferred_from_coro

from ariadne.browser import BrowserPool, set_browser_pool

logger = logging.getLogger(__name__)


class BrowserPoolExtension:
    def __init__(self, crawler):
        if not crawler.settings.getbool("ARIADNE_BROWSER_POOL_ENABLED", True):
            raise NotConfigured("ARIADNE_BROWSER_POOL_ENABLED is false")
        try:
            import playwright  # noqa: F401
        except ImportError as exc:
            raise NotConfigured("playwright not installed; pip install ariadne[browser]") from exc

        eng = crawler.settings.get("ARIADNE_ENGAGEMENT") or {}
        browser_cfg = ((eng.get("crawl") or {}).get("browser") or {})
        self.pool = BrowserPool(
            pool_size=int(
                browser_cfg.get("pool_size")
                or crawler.settings.getint("ARIADNE_BROWSER_POOL_SIZE", 4)
            ),
            checkout_timeout=float(
                browser_cfg.get("checkout_timeout_seconds")
                or crawler.settings.getfloat("ARIADNE_BROWSER_CHECKOUT_TIMEOUT", 60)
            ),
            execution_timeout=float(
                crawler.settings.getfloat("ARIADNE_BROWSER_EXECUTION_TIMEOUT", 180)
            ),
            max_contexts_served=int(
                browser_cfg.get("max_contexts_served")
                or crawler.settings.getint("ARIADNE_BROWSER_MAX_CONTEXTS_SERVED", 5000)
            ),
            headless=bool(
                browser_cfg.get("headless", crawler.settings.getbool("ARIADNE_BROWSER_HEADLESS", False))
            ),
            disable_webrtc=bool(browser_cfg.get("disable_webrtc", True)),
            proxy_dns=bool(browser_cfg.get("proxy_dns", True)),
        )
        self.crawler = crawler
        self._closing = False

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(crawler)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.engine_stopped, signal=signals.engine_stopped)
        return ext

    def spider_opened(self, spider):
        return deferred_from_coro(self._start(spider))

    async def _start(self, spider):
        await self.pool.start()
        set_browser_pool(self.pool)
        # Trap termination so Chromium closes before reactor dies
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._signal_handler)
            except ValueError:
                # Not in main thread
                pass
        atexit.register(self._atexit_close)
        spider.logger.info("BrowserPoolExtension: pool ready")

    def _signal_handler(self, signum, frame):
        logger.warning("Caught signal %s — closing BrowserPool before exit", signum)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._close_async())
        except Exception:
            pass

    def _atexit_close(self):
        if self._closing:
            return
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.pool.close())
            loop.close()
        except Exception as exc:
            logger.debug("atexit close: %s", exc)
        # Last resort: reap orphan Chromium if IPC already dead
        self._reap_orphans()

    @staticmethod
    def _reap_orphans():
        """Best-effort child Chromium reap when Playwright IPC is already dead."""
        import os
        import subprocess

        try:
            subprocess.run(
                ["pkill", "-P", str(os.getpid())],
                check=False,
                capture_output=True,
            )
        except Exception:
            pass
        for pattern in (
            "[c]hromium.*--remote-debugging-port",
            "[c]hrome.*--remote-debugging-port",
        ):
            try:
                subprocess.run(["pkill", "-f", pattern], check=False, capture_output=True)
            except Exception:
                pass

    async def _close_async(self):
        if self._closing:
            return
        self._closing = True
        await self.pool.close()
        set_browser_pool(None)

    def engine_stopped(self):
        """Close Playwright browsers BEFORE asyncio reactor finalizes."""
        if self._closing:
            return
        self._closing = True
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule and hope Scrapy waits — also run sync fallback via nest
                fut = asyncio.ensure_future(self.pool.close())
                # Best-effort: wait briefly
                try:
                    loop.run_until_complete(asyncio.wait_for(asyncio.shield(fut), timeout=5))
                except Exception:
                    pass
            else:
                loop.run_until_complete(self.pool.close())
        except Exception:
            try:
                asyncio.run(self.pool.close())
            except Exception as exc:
                logger.warning("engine_stopped pool close failed: %s", exc)
        set_browser_pool(None)
        logger.info("BrowserPoolExtension: pool stopped")

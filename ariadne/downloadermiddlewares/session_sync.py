"""Attach session_id, persona cookies; stagger post-solve sibling wake-ups."""

from __future__ import annotations

import logging
import random

from scrapy import signals
from scrapy.http import Request
from scrapy.utils.defer import deferred_from_coro

from ariadne.session import ChallengeState, get_session_sync

logger = logging.getLogger(__name__)


class SessionSyncMiddleware:
    def __init__(self, crawler):
        self.crawler = crawler
        self.priority = crawler.settings.getint("ARIADNE_ESCALATION_PRIORITY", 100)
        self.wait_delay = crawler.settings.getfloat("ARIADNE_CLEARANCE_WAIT_DELAY", 2.0)
        self.fresh_window = crawler.settings.getfloat("ARIADNE_CLEARANCE_FRESH_WINDOW", 5.0)
        self.stagger_base = crawler.settings.getfloat("ARIADNE_SIBLING_STAGGER_BASE", 0.5)
        self.stagger_max = crawler.settings.getfloat("ARIADNE_SIBLING_STAGGER_MAX", 5.0)
        self.stagger_jitter = crawler.settings.getbool("ARIADNE_SIBLING_STAGGER_JITTER", True)

    @classmethod
    def from_crawler(cls, crawler):
        mw = cls(crawler)
        crawler.signals.connect(mw.spider_opened, signal=signals.spider_opened)
        return mw

    def spider_opened(self, spider):
        spider.logger.debug("SessionSyncMiddleware ready")

    def process_request(self, request: Request):
        # Exit-IP canary: sticky proxy only — never bind target Session Sync artifacts
        if request.meta.get("ariadne_exit_ip_canary"):
            request.meta["ariadne_cookies"] = {}
            request.meta.pop("ariadne_persona", None)
            request.meta.pop("session_id", None)
            request.meta.pop("locked_to_mode", None)
            # Keep explicit sticky proxy from canary builder; do not overwrite
            return None

        try:
            sync = get_session_sync()
        except RuntimeError:
            return None

        sid = request.meta.get("session_id") or sync.session_id_for_url(request.url)
        sess = sync.get_or_create(sid)
        request.meta["session_id"] = sess.session_id

        # Franken-session guard: honor L3 lock
        requested = request.meta.get(
            "transport_mode",
            self.crawler.settings.get("ARIADNE_INITIAL_TRANSPORT", "L1_impersonate"),
        )
        mode = sync.effective_transport(sess.session_id, requested)
        request.meta["transport_mode"] = mode
        if sess.locked_to_mode:
            request.meta["locked_to_mode"] = sess.locked_to_mode

        request.meta["impersonate"] = sess.persona.impersonate_id
        request.meta["ariadne_persona"] = sess.persona.to_dict()
        # Never feed L3 vendor cookies into L1/L2 jar
        if mode == "L3_unlocker":
            request.meta["ariadne_cookies"] = dict(sess.l3_cookie_jar)
        else:
            request.meta["ariadne_cookies"] = sync.get_cookies(sess)
        request.meta["clearance_epoch"] = sess.clearance_epoch
        if sess.proxy_endpoint and not request.meta.get("proxy") and mode != "L3_unlocker":
            request.meta["proxy"] = sess.proxy_endpoint

        if request.meta.get("waiting_for_clearance"):
            state = sync.get_challenge_state(sess.session_id)
            if state == ChallengeState.SOLVING:
                # Re-schedule with delay; free this slot.
                request.meta["download_slot"] = f"wait:{sess.session_id}"
            elif state == ChallengeState.SOLVED:
                request.meta["waiting_for_clearance"] = False
                if mode == "L3_unlocker":
                    request.meta["ariadne_cookies"] = dict(sess.l3_cookie_jar)
                else:
                    request.meta["ariadne_cookies"] = sync.get_cookies(sess)
                request.meta["clearance_epoch"] = sess.clearance_epoch
                # Post-solve micro-herd: stagger fresh clearance wake-ups (§5.3.3)
                delay = self._sibling_stagger_delay(sync, sess.session_id, request)
                if delay > 0 and not request.meta.get("ariadne_stagger_done"):
                    request.meta["ariadne_stagger_done"] = True
                    request.meta["ariadne_stagger_delay"] = delay
                    logger.debug(
                        "Staggering post-solve wake for %s by %.2fs (session %s)",
                        request.url,
                        delay,
                        sess.session_id,
                    )
                    return deferred_from_coro(self._async_delay(delay))
            elif state == ChallengeState.FAILED:
                request.meta["waiting_for_clearance"] = False

        return None

    def _sibling_stagger_delay(self, sync, session_id: str, request: Request) -> float:
        age = sync.clearance_age_seconds(session_id)
        if age is None or age >= self.fresh_window:
            return 0.0
        idx = sync.next_sibling_wake_index(session_id)
        request.meta["ariadne_sibling_wake_index"] = idx
        if self.stagger_jitter:
            delay = random.uniform(self.stagger_base, self.stagger_max)
        else:
            delay = min(self.stagger_base * idx, self.stagger_max)
        return delay

    async def _async_delay(self, seconds: float) -> None:
        import asyncio

        await asyncio.sleep(seconds)

    def process_response(self, request, response):
        try:
            sync = get_session_sync()
        except RuntimeError:
            return response
        sid = request.meta.get("session_id")
        if not sid:
            return response
        sess = sync.get_or_create(sid)
        # Do not merge L3 vendor cookies into L1/L2 jar
        if request.meta.get("transport_mode_used") == "L3_unlocker" or sess.locked_to_mode == "L3_unlocker":
            return response
        cookies = request.meta.get("ariadne_response_cookies") or {}
        if cookies:
            sync.set_cookies(sess, cookies)
        return response

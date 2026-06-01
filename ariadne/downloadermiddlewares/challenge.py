"""Challenge detection with non-blocking high-priority re-schedule escalation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from scrapy.http import Request, Response

from ariadne.challenges import detect_challenge, looks_like_proxy_burn
from ariadne.items import DefenseEventItem
from ariadne.session import ChallengeState, get_session_sync

logger = logging.getLogger(__name__)


class ChallengeDetectMiddleware:
    def __init__(self, crawler):
        self.crawler = crawler
        self.priority = crawler.settings.getint("ARIADNE_ESCALATION_PRIORITY", 100)
        self.lease_ttl = crawler.settings.getfloat("ARIADNE_CHALLENGE_LEASE_TTL", 120)
        self.wait_delay = crawler.settings.getfloat("ARIADNE_CLEARANCE_WAIT_DELAY", 2.0)
        escalate = crawler.settings.get("ARIADNE_ENGAGEMENT") or {}
        transport = ((escalate.get("crawl") or {}).get("transport") or {})
        self.escalate_to = (transport.get("escalate_to") or ["L2_browser"])[0]

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_response(self, request: Request, response: Response, spider):
        mode = request.meta.get("transport_mode", "L1_impersonate")
        # Already on L2 stub/solve path — sync clearance if present
        if mode in {"L2_browser", "L3_unlocker"}:
            return self._finish_l2(request, response, spider)

        match = detect_challenge(response)
        if not match:
            if looks_like_proxy_burn(response):
                try:
                    sync = get_session_sync()
                    sid = request.meta.get("session_id")
                    if sid:
                        sync.burn_sticky_proxy(sid, reason=f"status={response.status}")
                        logger.warning("Proxy burn for session %s on %s", sid, request.url)
                except RuntimeError:
                    pass
            return response

        try:
            sync = get_session_sync()
        except RuntimeError:
            return response

        sid = request.meta.get("session_id") or sync.session_id_for_url(request.url)
        sync.get_or_create(sid)

        # Transparent sticky IP rotation: L1 re-challenge soon after a successful solve
        ip_window = self.crawler.settings.getfloat("ARIADNE_TRANSPARENT_IP_WINDOW", 60.0)
        max_burns = self.crawler.settings.getint("ARIADNE_TRANSPARENT_IP_MAX_BURNS", 3)
        if sync.maybe_transparent_ip_from_rechallenge(
            sid, window_seconds=ip_window, max_burns=max_burns
        ):
            logger.warning(
                "Transparent IP rotation detected for %s — burned sticky proxy", sid
            )
            request.meta.setdefault("defense_events", []).append(
                {
                    "type": "transparent_ip_rotation",
                    "url": request.url,
                    "session_id": sid,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            spider.crawler.stats.inc_value("ariadne/transparent_ip_rotation")

        spider.crawler.stats.inc_value(f"ariadne/challenge/{match.type}")

        event = DefenseEventItem(
            type=match.type,
            url=request.url,
            status=response.status,
            detail=match.detail,
            transport_mode=mode,
            proxy_class=request.meta.get("proxy"),
            session_id=sid,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        # Attach for spider to yield if desired
        request.meta.setdefault("defense_events", []).append(dict(event))

        got_lock = sync.try_begin_challenge(sid, lease_ttl=self.lease_ttl)
        pool_on = self.crawler.settings.getbool("ARIADNE_BROWSER_POOL_ENABLED", False)
        if got_lock:
            logger.info(
                "Escalating %s → %s for session %s (challenge=%s)",
                request.url,
                self.escalate_to,
                sid,
                match.type,
            )
            extra = {"escalate_from": mode}
            if not pool_on:
                extra["allow_l2_stub"] = True
            return self._reschedule(
                request,
                spider,
                transport_mode=self.escalate_to,
                waiting_for_clearance=False,
                extra_meta=extra,
            )

        logger.debug(
            "Session %s already solving; re-scheduling wait for %s",
            sid,
            request.url,
        )
        return self._reschedule(
            request,
            spider,
            transport_mode=mode,
            waiting_for_clearance=True,
            extra_meta={"download_delay": self.wait_delay},
        )

    def _finish_l2(self, request: Request, response: Response, spider):
        try:
            sync = get_session_sync()
        except RuntimeError:
            return response
        sid = request.meta.get("session_id")
        if not sid:
            return response
        sess = sync.get_or_create(sid)
        mode = request.meta.get("transport_mode") or request.meta.get("transport_mode_used")
        # Franken-session guard: never merge L3 vendor cookies into L1/L2 jar
        if mode != "L3_unlocker" and sess.locked_to_mode != "L3_unlocker":
            cookies = request.meta.get("ariadne_response_cookies") or {}
            if cookies:
                sync.set_cookies(sess, cookies)
        if response.status == 200 and not detect_challenge(response):
            sync.release_challenge(sid, ChallengeState.SOLVED)
        else:
            sync.release_challenge(sid, ChallengeState.FAILED)
        return response

    def _reschedule(
        self,
        request: Request,
        spider,
        *,
        transport_mode: str,
        waiting_for_clearance: bool,
        extra_meta: dict | None = None,
    ):
        """
        Free the downloader slot by replacing the response with a new high-priority Request.
        Scrapy downloader middlewares may return a Request to re-schedule.
        """
        meta = dict(request.meta)
        meta["transport_mode"] = transport_mode
        meta["waiting_for_clearance"] = waiting_for_clearance
        meta["escalated"] = True
        if extra_meta:
            meta.update(extra_meta)
        new_req = request.replace(
            meta=meta,
            dont_filter=True,
            priority=self.priority,
        )
        # Returning a Request from process_response is supported in Scrapy:
        # it schedules the request and drops the current response.
        return new_req

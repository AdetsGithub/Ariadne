"""Session Synchronization Service — shared persona, cookies, challenge mutex, proxy burn."""

from __future__ import annotations

import itertools
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from ariadne.stealth import Persona, create_persona_from_profile, list_impersonate_profiles


class ChallengeState(str, Enum):
    IDLE = "idle"
    SOLVING = "solving"
    SOLVED = "solved"
    FAILED = "failed"


@dataclass
class Session:
    session_id: str
    persona: Persona
    cookie_jar: dict[str, str] = field(default_factory=dict)
    # L3-only jar — NEVER merged into cookie_jar for L1/L2 de-escalation
    l3_cookie_jar: dict[str, str] = field(default_factory=dict)
    storage_state: dict[str, Any] | None = None
    proxy_endpoint: str | None = None
    challenge_state: ChallengeState = ChallengeState.IDLE
    clearance_epoch: int = 0
    clearance_solved_at: float | None = None  # wall time when challenge → solved
    clearance_exit_ip: str | None = None  # exit IP that acquired clearance (when known)
    transparent_ip_burns: int = 0
    clearance_meta: dict[str, Any] = field(default_factory=dict)
    locked_to_mode: str | None = None  # e.g. "L3_unlocker"
    _wake_seq: int = 0  # post-solve sibling stagger index
    _lock_holder: str | None = None
    _lock_expires_at: float = 0.0


class SessionSyncService:
    """In-process session store (Phase 1). Thread-safe for Scrapy concurrent downloads."""

    def __init__(
        self,
        *,
        impersonate_profiles: list[str] | None = None,
        proxy_list: list[str] | None = None,
        challenge_lease_ttl: float = 120.0,
        chromium_major: int | None = None,
        require_l2_anchor: bool = False,
    ) -> None:
        self.chromium_major = chromium_major
        self.require_l2_anchor = require_l2_anchor
        self._profiles = list_impersonate_profiles(
            impersonate_profiles,
            chromium_major=chromium_major,
            require_l2_anchor=require_l2_anchor,
        )
        if not self._profiles:
            raise ValueError("No impersonate profiles available after TLS-anchor filtering")
        self._proxy_cycle = itertools.cycle(proxy_list) if proxy_list else None
        self._proxy_list = list(proxy_list or [])
        self._challenge_lease_ttl = challenge_lease_ttl
        self._sessions: dict[str, Session] = {}
        self._guard = threading.RLock()

    def get_or_create(self, session_id: str | None = None, *, host: str | None = None) -> Session:
        with self._guard:
            sid = session_id if session_id else (f"host:{host}" if host else None)
            if not sid:
                raise ValueError("session_id or host required")
            if sid in self._sessions:
                self._expire_lock_if_needed(self._sessions[sid])
                return self._sessions[sid]
            persona = create_persona_from_profile(random.choice(self._profiles).profile_id)
            proxy = next(self._proxy_cycle) if self._proxy_cycle else None
            sess = Session(session_id=sid, persona=persona, proxy_endpoint=proxy)
            self._sessions[sid] = sess
            return sess

    def session_id_for_url(self, url: str) -> str:
        host = urlparse(url).hostname or "unknown"
        return f"host:{host}"

    def bind_persona(self, session: Session, persona: Persona) -> None:
        with self._guard:
            # Refuse personas not created via catalog factory path (profile_id check).
            create_persona_from_profile(persona.profile_id)
            session.persona = persona

    def get_cookies(self, session: Session) -> dict[str, str]:
        with self._guard:
            return dict(session.cookie_jar)

    def set_cookies(self, session: Session, cookies: dict[str, str]) -> None:
        with self._guard:
            session.cookie_jar.update(cookies)

    def get_storage_state(self, session: Session) -> dict[str, Any] | None:
        with self._guard:
            return session.storage_state

    def set_storage_state(self, session: Session, state: dict[str, Any] | None) -> None:
        with self._guard:
            session.storage_state = state

    def invalidate_clearance(self, session: Session, reason: str) -> None:
        with self._guard:
            for key in list(session.cookie_jar):
                lk = key.lower()
                if lk in {"cf_clearance", "_abck", "bm_sz", "ak_bmsc"} or "clearance" in lk:
                    del session.cookie_jar[key]
            session.storage_state = None
            session.clearance_meta = {"invalidated": reason, "at": time.time()}
            session.challenge_state = ChallengeState.IDLE

    def assert_coherent(self, session: Session) -> bool:
        with self._guard:
            expected = create_persona_from_profile(session.persona.profile_id)
            p = session.persona
            return (
                p.impersonate_id == expected.impersonate_id
                and p.user_agent == expected.user_agent
                and p.sec_ch_ua == expected.sec_ch_ua
            )

    def try_begin_challenge(self, session_id: str, lease_ttl: float | None = None) -> bool:
        ttl = lease_ttl if lease_ttl is not None else self._challenge_lease_ttl
        with self._guard:
            sess = self._sessions.get(session_id)
            if sess is None:
                return False
            self._expire_lock_if_needed(sess)
            if sess.challenge_state == ChallengeState.SOLVING:
                return False
            if sess.challenge_state not in {
                ChallengeState.IDLE,
                ChallengeState.FAILED,
                ChallengeState.SOLVED,
            }:
                return False
            # Allow re-solve from SOLVED if caller explicitly begins again after burn.
            sess.challenge_state = ChallengeState.SOLVING
            sess._lock_holder = "owner"
            sess._lock_expires_at = time.time() + ttl
            return True

    def release_challenge(self, session_id: str, state: ChallengeState) -> None:
        if state not in {ChallengeState.SOLVED, ChallengeState.FAILED}:
            raise ValueError("release_challenge state must be solved|failed")
        with self._guard:
            sess = self._sessions.get(session_id)
            if sess is None:
                return
            if state == ChallengeState.SOLVED:
                sess.clearance_epoch += 1
                sess.clearance_solved_at = time.time()
                sess._wake_seq = 0  # reset stagger for this clearance epoch
            sess.challenge_state = state
            sess._lock_holder = None
            sess._lock_expires_at = 0.0

    def set_clearance_exit_ip(self, session_id: str, exit_ip: str | None) -> None:
        with self._guard:
            sess = self._sessions.get(session_id)
            if sess is not None:
                sess.clearance_exit_ip = exit_ip

    def note_transparent_ip_rotation(
        self, session_id: str, *, max_burns: int = 3
    ) -> Session | None:
        """
        Passive/active detection of vendor exit-IP swap on a sticky endpoint.
        Burns sticky proxy if under max_burns; returns None if cap exceeded.
        """
        with self._guard:
            sess = self._sessions.get(session_id)
            if sess is None:
                return None
            if sess.transparent_ip_burns >= max_burns:
                sess.clearance_meta["transparent_ip_cap"] = {
                    "burns": sess.transparent_ip_burns,
                    "at": time.time(),
                }
                return None
            sess.transparent_ip_burns += 1
            sess.clearance_exit_ip = None
        return self.burn_sticky_proxy(session_id, reason="transparent_ip_rotation")

    def maybe_transparent_ip_from_rechallenge(
        self,
        session_id: str,
        *,
        window_seconds: float = 60.0,
        max_burns: int = 3,
    ) -> bool:
        """
        If clearance was just acquired and L1 immediately sees a challenge again,
        assume sticky endpoint's exit IP rotated. Returns True if burn applied.
        """
        with self._guard:
            sess = self._sessions.get(session_id)
            if sess is None or sess.clearance_solved_at is None:
                return False
            if sess.challenge_state != ChallengeState.SOLVED:
                return False
            age = time.time() - sess.clearance_solved_at
            if age > window_seconds:
                return False
        burned = self.note_transparent_ip_rotation(session_id, max_burns=max_burns)
        return burned is not None

    def next_sibling_wake_index(self, session_id: str) -> int:
        """Monotonic index for post-solve sibling stagger (0, 1, 2, …)."""
        with self._guard:
            sess = self._sessions.get(session_id)
            if sess is None:
                return 0
            idx = sess._wake_seq
            sess._wake_seq += 1
            return idx

    def clearance_age_seconds(self, session_id: str) -> float | None:
        """Seconds since clearance was acquired, or None if never solved."""
        with self._guard:
            sess = self._sessions.get(session_id)
            if sess is None or sess.clearance_solved_at is None:
                return None
            return max(0.0, time.time() - sess.clearance_solved_at)

    def get_challenge_state(self, session_id: str) -> ChallengeState:
        with self._guard:
            sess = self._sessions.get(session_id)
            if sess is None:
                return ChallengeState.IDLE
            self._expire_lock_if_needed(sess)
            return sess.challenge_state

    def clearance_epoch(self, session_id: str) -> int:
        with self._guard:
            sess = self._sessions.get(session_id)
            return sess.clearance_epoch if sess else 0

    def burn_sticky_proxy(self, session_id: str, reason: str) -> Session:
        """Drop IP-bound clearance, rotate proxy, keep persona, reset challenge for L2 re-escalate."""
        with self._guard:
            sess = self.get_or_create(session_id)
            self.invalidate_clearance(sess, reason=f"proxy_burn:{reason}")
            if self._proxy_list:
                # Pick a different endpoint when possible.
                candidates = [p for p in self._proxy_list if p != sess.proxy_endpoint]
                sess.proxy_endpoint = random.choice(candidates or self._proxy_list)
            else:
                sess.proxy_endpoint = None
            sess.challenge_state = ChallengeState.IDLE
            sess._lock_holder = None
            sess._lock_expires_at = 0.0
            sess.clearance_meta["proxy_burn"] = {"reason": reason, "at": time.time()}
            return sess

    def lock_to_mode(self, session_id: str, mode: str) -> Session:
        """Lock session to a transport (e.g. L3_unlocker). Prevents Franken-session de-escalation."""
        with self._guard:
            sess = self.get_or_create(session_id)
            sess.locked_to_mode = mode
            sess.clearance_meta["locked_to_mode"] = {"mode": mode, "at": time.time()}
            return sess

    def set_l3_cookies(self, session: Session, cookies: dict[str, str]) -> None:
        """Store unlocker cookies in the L3-only jar — never merge into L1/L2 cookie_jar."""
        with self._guard:
            session.l3_cookie_jar.update(cookies)

    def burn_session(self, session_id: str, reason: str) -> None:
        """Destroy session state so a fresh session_id must be used (required to leave L3)."""
        with self._guard:
            self._sessions.pop(session_id, None)

    def effective_transport(self, session_id: str, requested: str) -> str:
        """Honor locked_to_mode over the requested transport."""
        with self._guard:
            sess = self._sessions.get(session_id)
            if sess and sess.locked_to_mode:
                return sess.locked_to_mode
            return requested

    def _expire_lock_if_needed(self, sess: Session) -> None:
        if (
            sess.challenge_state == ChallengeState.SOLVING
            and sess._lock_expires_at
            and time.time() > sess._lock_expires_at
        ):
            sess.challenge_state = ChallengeState.FAILED
            sess._lock_holder = None
            sess._lock_expires_at = 0.0


# Process-global handle set by SessionSyncExtension
_SERVICE: SessionSyncService | None = None


def get_session_sync() -> SessionSyncService:
    if _SERVICE is None:
        raise RuntimeError("SessionSyncService not initialized (is SessionSyncExtension enabled?)")
    return _SERVICE


def set_session_sync(service: SessionSyncService | None) -> None:
    global _SERVICE
    _SERVICE = service
"""Challenge / WAF page signature detection (Phase 1 heuristics)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from scrapy.http import Response

CHALLENGE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cloudflare", re.compile(r"cf-browser-verification|just a moment|cf-challenge|turnstile", re.I)),
    ("cloudflare", re.compile(r"cdn-cgi/challenge-platform", re.I)),
    ("datadome", re.compile(r"datadome|dd\.js|geo\.captcha-delivery\.com", re.I)),
    ("akamai", re.compile(r"_abck|akamai|edgesuite", re.I)),
    ("perimeterx", re.compile(r"perimeterx|humansecurity|px-captcha", re.I)),
    ("captcha", re.compile(r"recaptcha|hcaptcha|g-recaptcha", re.I)),
]


@dataclass
class ChallengeMatch:
    type: str
    detail: str


def detect_challenge(response: Response) -> ChallengeMatch | None:
    """Return a ChallengeMatch if the response looks like a bot challenge / block page."""
    status = response.status
    body = ""
    try:
        body = response.text[:50_000]
    except Exception:
        body = ""

    # Soft signals on status
    if status in {403, 429, 503}:
        for ctype, pat in CHALLENGE_PATTERNS:
            if pat.search(body) or pat.search(response.headers.get(b"server", b"").decode("latin-1", "ignore")):
                return ChallengeMatch(type=ctype, detail=f"status={status} pattern={pat.pattern[:40]}")
        if status == 403 and _looks_like_interstitial(body):
            return ChallengeMatch(type="unknown", detail="status=403 interstitial-like body")

    for ctype, pat in CHALLENGE_PATTERNS:
        if pat.search(body):
            # Avoid false positives on normal pages that merely mention reCAPTCHA in footer docs
            if ctype == "captcha" and status == 200 and "g-recaptcha" not in body.lower():
                continue
            if status == 200 and ctype in {"akamai"} and "_abck" not in body.lower():
                # header-only mentions are weak; require body token for 200
                if not re.search(r"access.?denied|bot.?detect", body, re.I):
                    continue
            return ChallengeMatch(type=ctype, detail=f"body match status={status}")

    title = ""
    m = re.search(r"<title[^>]*>([^<]+)</title>", body, re.I)
    if m:
        title = m.group(1).strip().lower()
    if title in {"just a moment...", "attention required! attention required!", "access denied"}:
        return ChallengeMatch(type="cloudflare", detail=f"title={title}")

    return None


def _looks_like_interstitial(body: str) -> bool:
    if len(body) < 500:
        return True
    return bool(re.search(r"challenge|captcha|cf-|ddos|checking your browser", body, re.I))


def looks_like_proxy_burn(response: Response) -> bool:
    """Heuristic: hard block without JS challenge body → sticky IP may be burned."""
    if response.status not in {403, 407, 502, 522}:
        return False
    body = ""
    try:
        body = response.text[:8_000].lower()
    except Exception:
        return True
    # If we see an interactive challenge, it's not a simple IP burn.
    if detect_challenge(response):
        return False
    return "forbidden" in body or body.strip() == "" or len(body) < 200
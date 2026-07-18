"""Playwright Chromium version detection — immutable TLS/H2 fingerprint anchor for L1↔L2.

Playwright cannot spoof JA3/H2; curl_cffi can. Session Sync MUST only emit L1 personas
whose Chromium major matches the bundled Playwright Chromium, or clearance cookies
will be invalidated on handoff (Akamai/CF IP+fingerprint binding).
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)


class ChromiumAnchorError(RuntimeError):
    """Raised when Playwright Chromium cannot be resolved or no catalog profile matches."""


@lru_cache(maxsize=1)
def detect_playwright_chromium_major() -> int | None:
    """Return major version of Playwright's bundled Chromium, or None if Playwright missing."""
    try:
        from playwright._impl._driver import compute_driver_executable  # noqa: F401
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.info("Playwright not installed — Chromium TLS anchor unavailable (L1-only mode)")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                version = browser.version  # e.g. "131.0.6778.33" or "Chrome/131.0..."
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("Failed to launch Playwright Chromium for version detect: %s", exc)
        return None

    return parse_chromium_major(version)


def parse_chromium_major(version: str) -> int | None:
    if not version:
        return None
    # "131.0.6778.33" or "Chrome/131.0.6778.33"
    m = re.search(r"(?:Chrome/)?(\d+)\.", version)
    if m:
        return int(m.group(1))
    m = re.search(r"^(\d+)$", version.strip())
    return int(m.group(1)) if m else None


def resolve_anchor_profile_ids(
    *,
    chromium_major: int | None,
    catalog_profile_ids: list[str],
    profile_majors: dict[str, int | None],
    allowlist: list[str] | None = None,
) -> list[str]:
    """
    Filter catalog to profiles compatible with Playwright Chromium major.

    If chromium_major is None (no Playwright), return allowlist or full catalog (L1-only).
    If Playwright is present, prefer exact chromium_major matches; when curl_cffi lags
    Playwright, fall back to the nearest catalog major ≤ the anchor (with a warning).
    """
    candidates = list(allowlist) if allowlist else list(catalog_profile_ids)
    if chromium_major is None:
        return candidates

    matched = [
        pid
        for pid in candidates
        if profile_majors.get(pid) == chromium_major
    ]
    if matched:
        return matched

    lower = [
        (profile_majors[pid], pid)
        for pid in candidates
        if profile_majors.get(pid) is not None and profile_majors[pid] <= chromium_major
    ]
    if lower:
        best_major = max(maj for maj, _ in lower)
        nearest = [pid for maj, pid in lower if maj == best_major]
        logger.warning(
            "No curl_cffi catalog profile matches Playwright Chromium major %s; "
            "using nearest catalog major %s (%s). Clearance handoff may be fragile — "
            "upgrade profiles.yaml / curl_cffi when an exact match exists.",
            chromium_major,
            best_major,
            nearest,
        )
        return nearest

    raise ChromiumAnchorError(
        f"No curl_cffi catalog profile matches Playwright Chromium major {chromium_major}. "
        f"Available majors: {sorted({v for v in profile_majors.values() if v})} "
        f"(profile ids: {sorted(catalog_profile_ids)}). "
        "Upgrade profiles.yaml / curl_cffi so L1 JA3 matches L2's real TLS fingerprint."
    )


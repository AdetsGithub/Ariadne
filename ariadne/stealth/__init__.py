"""Profile catalog and persona factory — curl_cffi profile derived from Playwright Chromium anchor."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from ariadne.stealth.chromium import resolve_anchor_profile_ids


@dataclass(frozen=True)
class ProfileMeta:
    profile_id: str
    impersonate: str
    user_agent: str
    sec_ch_ua: str | None
    sec_ch_ua_mobile: str | None
    sec_ch_ua_platform: str | None
    accept_language: str
    viewport: dict[str, int]
    family: str
    chromium_major: int | None = None
    l2_compatible: bool = True


@dataclass
class Persona:
    profile_id: str
    impersonate_id: str
    user_agent: str
    sec_ch_ua: str | None
    sec_ch_ua_mobile: str | None
    sec_ch_ua_platform: str | None
    accept_language: str
    viewport: dict[str, int]
    family: str
    locale: str = "en-US"
    timezone_id: str = "America/New_York"
    chromium_major: int | None = None

    def headers(self, *, referer: str | None = None, fetch_site: str = "none") -> dict[str, str]:
        h: dict[str, str] = {
            "User-Agent": self.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": self.accept_language,
            "Accept-Encoding": "gzip, deflate, br",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": fetch_site,
            "Sec-Fetch-User": "?1",
            "Connection": "keep-alive",
        }
        if self.sec_ch_ua:
            h["Sec-CH-UA"] = self.sec_ch_ua
        if self.sec_ch_ua_mobile is not None:
            h["Sec-CH-UA-Mobile"] = self.sec_ch_ua_mobile
        if self.sec_ch_ua_platform:
            h["Sec-CH-UA-Platform"] = self.sec_ch_ua_platform
        if referer:
            h["Referer"] = referer
        return h

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "impersonate_id": self.impersonate_id,
            "user_agent": self.user_agent,
            "sec_ch_ua": self.sec_ch_ua,
            "sec_ch_ua_mobile": self.sec_ch_ua_mobile,
            "sec_ch_ua_platform": self.sec_ch_ua_platform,
            "accept_language": self.accept_language,
            "viewport": self.viewport,
            "family": self.family,
            "locale": self.locale,
            "timezone_id": self.timezone_id,
            "chromium_major": self.chromium_major,
        }


def _load_yaml(path: Path | None = None) -> dict[str, Any]:
    if path is not None:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        ref = resources.files("ariadne.stealth").joinpath("profiles.yaml")
        with ref.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except (FileNotFoundError, ModuleNotFoundError, TypeError):
        local = Path(__file__).with_name("profiles.yaml")
        return yaml.safe_load(local.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_profile_catalog(path: str | None = None) -> dict[str, ProfileMeta]:
    raw = _load_yaml(Path(path) if path else None)
    profiles = raw.get("profiles") or {}
    out: dict[str, ProfileMeta] = {}
    for pid, meta in profiles.items():
        major = meta.get("chromium_major")
        l2 = meta.get("l2_compatible", major is not None)
        out[pid] = ProfileMeta(
            profile_id=pid,
            impersonate=meta["impersonate"],
            user_agent=meta["user_agent"],
            sec_ch_ua=meta.get("sec_ch_ua"),
            sec_ch_ua_mobile=meta.get("sec_ch_ua_mobile"),
            sec_ch_ua_platform=meta.get("sec_ch_ua_platform"),
            accept_language=meta.get("accept_language", "en-US,en;q=0.9"),
            viewport=dict(meta.get("viewport") or {"width": 1920, "height": 1080}),
            family=meta.get("family", "chrome"),
            chromium_major=int(major) if major is not None else None,
            l2_compatible=bool(l2),
        )
    return out


def clear_profile_catalog_cache() -> None:
    load_profile_catalog.cache_clear()


def list_impersonate_profiles(
    allowlist: list[str] | None = None,
    *,
    chromium_major: int | None = None,
    require_l2_anchor: bool = False,
) -> list[ProfileMeta]:
    """
    List usable profiles.

    When require_l2_anchor=True (Playwright L2 enabled), filter to profiles whose
    chromium_major matches Playwright's bundled Chromium — the immutable TLS anchor.
    """
    catalog = load_profile_catalog()
    majors = {pid: m.chromium_major for pid, m in catalog.items()}
    if require_l2_anchor or chromium_major is not None:
        ids = resolve_anchor_profile_ids(
            chromium_major=chromium_major,
            catalog_profile_ids=list(catalog.keys()),
            profile_majors=majors,
            allowlist=allowlist,
        )
        # Drop explicitly L2-incompatible (e.g. firefox) even if major matched somehow
        return [catalog[i] for i in ids if catalog[i].l2_compatible or not require_l2_anchor]

    if allowlist:
        missing = [p for p in allowlist if p not in catalog]
        if missing:
            raise ValueError(f"Unknown impersonate profiles (not in catalog): {missing}")
        return [catalog[p] for p in allowlist]
    return list(catalog.values())


def create_persona_from_profile(profile_id: str) -> Persona:
    catalog = load_profile_catalog()
    if profile_id not in catalog:
        raise ValueError(
            f"Cannot create persona for unknown profile {profile_id!r}. "
            f"Known: {sorted(catalog)}"
        )
    m = catalog[profile_id]
    return Persona(
        profile_id=m.profile_id,
        impersonate_id=m.impersonate,
        user_agent=m.user_agent,
        sec_ch_ua=m.sec_ch_ua,
        sec_ch_ua_mobile=m.sec_ch_ua_mobile,
        sec_ch_ua_platform=m.sec_ch_ua_platform,
        accept_language=m.accept_language,
        viewport=dict(m.viewport),
        family=m.family,
        chromium_major=m.chromium_major,
    )


def assert_catalog_subset_of(supported: set[str]) -> list[str]:
    catalog = load_profile_catalog()
    return sorted(pid for pid in catalog if catalog[pid].impersonate not in supported)

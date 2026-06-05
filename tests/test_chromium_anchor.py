"""Chromium TLS anchor — Playwright major gates curl_cffi profile selection."""

import pytest

from ariadne.stealth import list_impersonate_profiles, load_profile_catalog
from ariadne.stealth.chromium import (
    ChromiumAnchorError,
    parse_chromium_major,
    resolve_anchor_profile_ids,
)


def test_parse_chromium_major():
    assert parse_chromium_major("131.0.6778.33") == 131
    assert parse_chromium_major("Chrome/124.0.0.0") == 124


def test_anchor_filters_to_matching_major():
    catalog = load_profile_catalog()
    majors = {pid: m.chromium_major for pid, m in catalog.items()}
    ids = resolve_anchor_profile_ids(
        chromium_major=131,
        catalog_profile_ids=list(catalog.keys()),
        profile_majors=majors,
    )
    assert ids == ["chrome131"]


def test_anchor_raises_when_no_match():
    catalog = load_profile_catalog()
    majors = {pid: m.chromium_major for pid, m in catalog.items()}
    with pytest.raises(ChromiumAnchorError):
        resolve_anchor_profile_ids(
            chromium_major=999,
            catalog_profile_ids=list(catalog.keys()),
            profile_majors=majors,
        )


def test_list_profiles_require_l2_anchor():
    profiles = list_impersonate_profiles(chromium_major=124, require_l2_anchor=True)
    assert len(profiles) == 1
    assert profiles[0].profile_id == "chrome124"
    assert profiles[0].l2_compatible


def test_session_sync_uses_anchor():
    from ariadne.session import SessionSyncService

    svc = SessionSyncService(chromium_major=131, require_l2_anchor=True)
    sess = svc.get_or_create("host:anchored.test")
    assert sess.persona.profile_id == "chrome131"
    assert sess.persona.chromium_major == 131

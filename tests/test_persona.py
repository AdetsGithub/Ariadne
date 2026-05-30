"""Unit tests: profile → persona factory."""

import pytest

from ariadne.stealth import (
    create_persona_from_profile,
    list_impersonate_profiles,
    load_profile_catalog,
)


def test_catalog_loads():
    catalog = load_profile_catalog()
    assert "chrome124" in catalog
    assert "chrome131" in catalog


def test_persona_derived_from_profile():
    p = create_persona_from_profile("chrome124")
    assert p.impersonate_id == "chrome124"
    assert "Chrome/124" in p.user_agent
    assert p.sec_ch_ua is not None
    headers = p.headers()
    assert headers["User-Agent"] == p.user_agent
    assert headers["Sec-CH-UA"] == p.sec_ch_ua


def test_unknown_profile_rejected():
    with pytest.raises(ValueError, match="unknown profile"):
        create_persona_from_profile("chrome999")


def test_allowlist_filters():
    profiles = list_impersonate_profiles(["chrome124"])
    assert len(profiles) == 1
    assert profiles[0].profile_id == "chrome124"


def test_allowlist_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown impersonate"):
        list_impersonate_profiles(["not-a-real-profile"])

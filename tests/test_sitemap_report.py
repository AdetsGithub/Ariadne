"""Tests for sitemap union report."""

import json
from pathlib import Path

from ariadne.reporting.sitemap import build_sitemap_entries, normalize_url, write_sitemap_report


def test_normalize_url():
    assert normalize_url("https://Ex.Com/a#frag") == "https://ex.com/a"
    assert "q=1" in normalize_url("https://ex.com/s?q=1")


def test_build_prefers_page_over_candidate(tmp_path: Path):
    (tmp_path / "PageItem.ndjson").write_text(
        json.dumps({"url": "https://ex.com/a", "status": 200, "discovery_source": "link"})
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "UrlCandidateItem.ndjson").write_text(
        json.dumps({"url": "https://ex.com/a", "source": "sitemap", "scheduled": True})
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "OutboundLinkItem.ndjson").write_text(
        json.dumps({"url": "https://other.com/x", "host": "other.com", "parent_url": "https://ex.com/a"})
        + "\n",
        encoding="utf-8",
    )
    entries = build_sitemap_entries(tmp_path)
    by_url = {e["url"]: e for e in entries}
    assert by_url["https://ex.com/a"]["kind"] == "page"
    assert by_url["https://other.com/x"]["kind"] == "outbound"
    assert by_url["https://other.com/x"]["fetched"] is False


def test_write_sitemap_report(tmp_path: Path):
    (tmp_path / "FailedUrlItem.ndjson").write_text(
        json.dumps(
            {
                "url": "https://ex.com/gone",
                "error_type": "download",
                "error_detail": "curl 56",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    jsonl, md, counts = write_sitemap_report(tmp_path)
    assert jsonl.exists() and md.exists()
    assert counts.get("failed") == 1

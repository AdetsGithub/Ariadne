"""Unit tests for sitemap XML / robots Sitemap: parsing."""

from ariadne.discovery.sitemaps import (
    default_sitemap_guess,
    extract_sitemap_locs_from_robots,
    parse_sitemap_xml,
)


def test_robots_sitemap_directives():
    text = """
User-agent: *
Disallow: /admin
Sitemap: https://example.com/sitemap.xml
Sitemap: /other-sitemap.xml
"""
    locs = extract_sitemap_locs_from_robots(text)
    assert locs == [
        "https://example.com/sitemap.xml",
        "/other-sitemap.xml",
    ]


def test_parse_urlset():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc></url>
  <url><loc>https://example.com/b</loc></url>
</urlset>
"""
    urls, children = parse_sitemap_xml(xml, base_url="https://example.com/")
    assert children == []
    assert urls == ["https://example.com/a", "https://example.com/b"]


def test_parse_sitemap_index():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-1.xml</loc></sitemap>
  <sitemap><loc>/sitemap-2.xml</loc></sitemap>
</sitemapindex>
"""
    urls, children = parse_sitemap_xml(xml, base_url="https://example.com/")
    assert urls == []
    assert children == [
        "https://example.com/sitemap-1.xml",
        "https://example.com/sitemap-2.xml",
    ]


def test_default_sitemap_guess():
    assert default_sitemap_guess("https://example.com") == "https://example.com/sitemap.xml"

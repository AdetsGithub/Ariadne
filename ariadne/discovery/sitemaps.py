"""Parse sitemap.xml / sitemap index documents into absolute URL lists.

Supports the common sitemap.org schemas:
- urlset  → page (or asset) loc entries
- sitemapindex → nested sitemap loc entries (caller fetches recursively)

Does not perform HTTP itself — keep I/O in spiders / middlewares.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Strip namespaces so we can match local tag names across vendors.
_NS_RE = re.compile(r"\{[^}]+\}")


def _local(tag: str) -> str:
    return _NS_RE.sub("", tag)


def extract_sitemap_locs_from_robots(robots_text: str) -> list[str]:
    """Return Sitemap: directives from a robots.txt body (absolute or relative)."""
    locs: list[str] = []
    for line in robots_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("sitemap:"):
            loc = stripped.split(":", 1)[1].strip()
            if loc:
                locs.append(loc)
    return locs


def parse_sitemap_xml(body: str | bytes, *, base_url: str = "") -> tuple[list[str], list[str]]:
    """
    Parse a sitemap document.

    Returns:
        (page_or_url_locs, child_sitemap_locs)
    """
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = body
    text = text.lstrip()
    if not text:
        return [], []

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        logger.debug("sitemap XML parse failed for %s: %s", base_url, exc)
        return [], []

    urls: list[str] = []
    children: list[str] = []
    root_name = _local(root.tag).lower()

    if root_name == "sitemapindex":
        for el in root.iter():
            if _local(el.tag).lower() == "loc" and el.text:
                loc = el.text.strip()
                if loc:
                    children.append(urljoin(base_url, loc))
        return [], children

    # Default: treat as urlset (or unknown with <loc> under <url>)
    for el in root.iter():
        if _local(el.tag).lower() != "url":
            continue
        for child in el:
            if _local(child.tag).lower() == "loc" and child.text:
                loc = child.text.strip()
                if loc:
                    urls.append(urljoin(base_url, loc))

    # Fallback: any top-level loc if not structured as url/sitemapindex
    if not urls and not children:
        for el in root.iter():
            if _local(el.tag).lower() == "loc" and el.text:
                loc = urljoin(base_url, el.text.strip())
                # Heuristic: .xml paths are nested sitemaps
                path = (urlparse(loc).path or "").lower()
                if path.endswith(".xml") or "sitemap" in path:
                    children.append(loc)
                else:
                    urls.append(loc)

    return urls, children


def default_sitemap_guess(origin: str) -> str:
    """Conventional /sitemap.xml next to the site origin."""
    origin = origin.rstrip("/") + "/"
    return urljoin(origin, "sitemap.xml")

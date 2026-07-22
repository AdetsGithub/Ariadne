"""HTML discovery helpers: assets, outbound links, JS path hints, form seeds."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from scrapy.http import Response

from ariadne.discovery import host_allowed, is_asset_url

# Conservative path-like strings inside scripts (SPA route hints).
_JS_PATH_RE = re.compile(
    r"""['"`](/(?:[a-zA-Z0-9_\-.~]+/?)+)['"`]"""
)


def discovery_settings(spider) -> dict:
    raw = spider.settings.get("ARIADNE_DISCOVERY") or {}
    if isinstance(raw, dict):
        return raw
    return {}


def iter_anchor_links(response: Response):
    """Yield (absolute_url, link_text, tag_html) for a[href] on HTML pages."""
    for a in response.css("a[href]"):
        href = a.attrib.get("href")
        if not href or href.startswith(("mailto:", "javascript:", "#", "tel:")):
            continue
        url = urljoin(response.url, href)
        text = "".join(a.css("::text").getall()).strip()
        yield url, text, a.get()


def classify_link(url: str, allow_domains: list[str]) -> str:
    """Return 'in_scope' | 'outbound' | 'asset' | 'invalid'."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "invalid"
    host = parsed.hostname or ""
    if not host:
        return "invalid"
    if is_asset_url(url):
        return "asset"
    if not host_allowed(host, allow_domains):
        return "outbound"
    return "in_scope"


def iter_asset_refs(response: Response):
    """Yield (absolute_url, source_tag) for common static asset references."""
    specs = [
        ("img[src]", "src", "img"),
        ("script[src]", "src", "script"),
        ("link[href]", "href", "link"),
        ("source[src]", "src", "source"),
        ("video[src]", "src", "video"),
        ("audio[src]", "src", "audio"),
        ("embed[src]", "src", "embed"),
        ("object[data]", "data", "object"),
    ]
    for css, attr, source in specs:
        for el in response.css(css):
            href = el.attrib.get(attr)
            if not href or href.startswith(("data:", "blob:", "javascript:")):
                continue
            url = urljoin(response.url, href)
            if urlparse(url).scheme in {"http", "https"}:
                yield url, source


def extract_js_path_hints(response: Response, *, limit: int = 50) -> list[str]:
    """Best-effort absolute URLs from path-like string literals in script bodies."""
    found: list[str] = []
    seen: set[str] = set()
    chunks: list[str] = []
    for script in response.css("script"):
        src = script.attrib.get("src")
        if src:
            continue  # external bodies not inlined
        text = script.xpath("string()").get() or ""
        if text.strip():
            chunks.append(text[:100_000])
    blob = "\n".join(chunks)[:200_000]
    for m in _JS_PATH_RE.finditer(blob):
        path = m.group(1)
        if is_asset_url(path):
            continue
        if any(x in path for x in ("{", "}", "<", ">")):
            continue
        abs_url = urljoin(response.url, path)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        found.append(abs_url)
        if len(found) >= limit:
            break
    return found


def iter_get_form_actions(response: Response):
    """Yield absolute action URLs for GET forms (search endpoints, etc.)."""
    for form in response.css("form"):
        method = (form.attrib.get("method") or "GET").upper()
        if method != "GET":
            continue
        action = form.attrib.get("action") or ""
        url = urljoin(response.url, action or response.url)
        if urlparse(url).scheme in {"http", "https"}:
            yield url

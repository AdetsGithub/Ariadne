"""Shared URL / depth helpers for map-family spiders and discovery."""

from __future__ import annotations

from urllib.parse import urlparse

# Extensions treated as static assets (not HTML pages) for discovery.
ASSET_EXTENSIONS: tuple[str, ...] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".webm",
    ".mp3",
    ".pdf",
    ".zip",
    ".gz",
    ".tgz",
    ".rar",
    ".7z",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
)


def normalize_max_depth(raw) -> int | None:
    """Return int depth limit, or None for unlimited."""
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip().lower() in {"", "null", "none", "unlimited"}:
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 5
    if n < 0:
        return None
    return n


def depth_allows_follow(current_depth: int, max_depth: int | None) -> bool:
    """True if we may enqueue children from a page at current_depth."""
    if max_depth is None:
        return True
    return current_depth < max_depth


def is_asset_url(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    return any(path.endswith(ext) for ext in ASSET_EXTENSIONS)


def host_allowed(host: str, allow_domains: list[str]) -> bool:
    if not allow_domains:
        return True
    return any(host == d or host.endswith("." + d) for d in allow_domains)

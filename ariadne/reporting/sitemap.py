"""Union NDJSON discovery artifacts into a canonical sitemap inventory.

Priority when the same URL appears in multiple files (highest wins):
  PageItem > AssetItem > EndpointItem > UrlCandidateItem > FailedUrlItem > OutboundLinkItem
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urlsplit, urlunsplit

# Lower number = higher priority when merging duplicate URLs.
_SOURCE_PRIORITY = {
    "page": 0,
    "asset": 1,
    "endpoint": 2,
    "candidate": 3,
    "failed": 4,
    "outbound": 5,
}

_FILE_MAP = [
    ("PageItem.ndjson", "page"),
    ("AssetItem.ndjson", "asset"),
    ("EndpointItem.ndjson", "endpoint"),
    ("UrlCandidateItem.ndjson", "candidate"),
    ("FailedUrlItem.ndjson", "failed"),
    ("OutboundLinkItem.ndjson", "outbound"),
]


def normalize_url(url: str) -> str:
    """Strip fragment; keep query (search endpoints matter)."""
    if not url:
        return ""
    bare, _frag = urldefrag(url)
    parts = urlsplit(bare)
    # Drop default ports
    netloc = parts.netloc
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc.lower(), path, parts.query, ""))


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _row_url(row: dict[str, Any], kind: str) -> str:
    if kind == "outbound":
        return row.get("url") or ""
    return row.get("final_url") or row.get("url") or ""


def build_sitemap_entries(artifacts_dir: Path) -> list[dict[str, Any]]:
    """Merge artifact NDJSON into deduped sitemap entries."""
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for filename, kind in _FILE_MAP:
        for row in _load_rows(artifacts_dir / filename):
            url = normalize_url(_row_url(row, kind))
            if not url:
                continue
            entry = {
                "url": url,
                "kind": kind,
                "status": row.get("status") or row.get("http_status"),
                "source": row.get("discovery_source")
                or row.get("source")
                or row.get("error_type")
                or kind,
                "parent_url": row.get("parent_url") or row.get("page_url"),
                "host": row.get("host"),
                "fetched": kind in {"page", "asset", "endpoint"},
                "error": row.get("error_detail") if kind == "failed" else None,
            }
            pri = _SOURCE_PRIORITY[kind]
            prev = best.get(url)
            if prev is None or pri < prev[0]:
                best[url] = (pri, entry)
    return [e for _, e in sorted(best.values(), key=lambda t: t[1]["url"])]


def write_sitemap_report(artifacts_dir: Path) -> tuple[Path, Path, dict[str, int]]:
    """Write sitemap.jsonl + sitemap.md; return paths and counts by kind."""
    entries = build_sitemap_entries(artifacts_dir)
    jsonl = artifacts_dir / "sitemap.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, default=str) + "\n")

    counts = Counter(e["kind"] for e in entries)
    fetched = sum(1 for e in entries if e.get("fetched"))
    failed = counts.get("failed", 0)
    outbound = counts.get("outbound", 0)
    md_lines = [
        "# Ariadne sitemap inventory",
        "",
        f"- Total unique URLs: **{len(entries)}**",
        f"- Fetched (page/asset/endpoint): **{fetched}**",
        f"- Failed attempts: **{failed}**",
        f"- Outbound (recorded, not fetched): **{outbound}**",
        "",
        "## By kind",
        "",
    ]
    for kind, n in sorted(counts.items()):
        md_lines.append(f"- `{kind}`: {n}")
    md_lines.extend(
        [
            "",
            "This is a **best-effort** union of crawl artifacts, not a guarantee of",
            "every possible site URL (SPA routers, auth trees, search query space).",
            "See [docs/SITEMAP.md](../../docs/SITEMAP.md).",
            "",
            f"Machine-readable: `{jsonl.name}`",
        ]
    )
    md_path = artifacts_dir / "sitemap.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return jsonl, md_path, dict(counts)

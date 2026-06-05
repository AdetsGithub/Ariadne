"""Playwright network capture with MAX_BODY_SIZE guard (apisnoop OOM prevention)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_MAX_BODY_SIZE = 2 * 1024 * 1024  # 2 MiB


def _content_length(headers: dict[str, str]) -> int | None:
    raw = headers.get("content-length") or headers.get("Content-Length")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def attach_network_sniffer(
    page: Any,
    *,
    bucket: list[dict[str, Any]],
    max_body_size: int = DEFAULT_MAX_BODY_SIZE,
    include_resource_types: set[str] | None = None,
) -> None:
    """
    Record XHR/fetch (and optionally other) responses into `bucket`.

    If Content-Length exceeds max_body_size, capture headers/url/method only and DROP the body.
    """
    allowed = include_resource_types or {"xhr", "fetch"}

    async def on_response(response: Any) -> None:
        try:
            req = response.request
            rtype = req.resource_type
            if rtype not in allowed:
                return
            headers = await response.all_headers()
            entry: dict[str, Any] = {
                "url": response.url,
                "method": req.method,
                "status": response.status,
                "resource_type": rtype,
                "content_type": headers.get("content-type") or headers.get("Content-Type"),
                "headers": {k: v for k, v in headers.items() if k.lower() in {
                    "content-type", "content-length", "server", "cache-control"
                }},
                "body": None,
                "body_truncated": False,
            }
            cl = _content_length(headers)
            if cl is not None and cl > max_body_size:
                entry["body_truncated"] = True
                entry["body_bytes"] = cl
                bucket.append(entry)
                return

            # Unknown length — attempt body with size guard
            try:
                body = await response.body()
            except Exception:
                bucket.append(entry)
                return
            if len(body) > max_body_size:
                entry["body_truncated"] = True
                entry["body_bytes"] = len(body)
            else:
                # Only keep text-ish bodies
                ctype = (entry["content_type"] or "").lower()
                if any(t in ctype for t in ("json", "text", "javascript", "xml", "html")):
                    try:
                        entry["body"] = body.decode("utf-8", errors="replace")[:max_body_size]
                    except Exception:
                        entry["body_truncated"] = True
                        entry["body_bytes"] = len(body)
                else:
                    entry["body_truncated"] = True
                    entry["body_bytes"] = len(body)
            bucket.append(entry)
        except Exception as exc:
            logger.debug("network sniffer error: %s", exc)

    page.on("response", lambda response: asyncio_safe_create(on_response(response)))


def asyncio_safe_create(coro: Any) -> None:
    try:
        loop = asyncio_get_running()
        loop.create_task(coro)
    except Exception:
        pass


def asyncio_get_running():
    import asyncio

    return asyncio.get_running_loop()


def endpoints_from_bucket(bucket: list[dict[str, Any]], *, source: str = "network") -> list[dict[str, Any]]:
    out = []
    for e in bucket:
        parsed = urlparse(e["url"])
        params = []
        if parsed.query:
            for part in parsed.query.split("&"):
                if "=" in part:
                    k, _, v = part.partition("=")
                    params.append({"name": k, "example": v[:80]})
        out.append(
            {
                "url": e["url"],
                "method": e.get("method"),
                "source": source,
                "content_type": e.get("content_type"),
                "parameters": params,
                "status": e.get("status"),
                "body_truncated": e.get("body_truncated", False),
                "sample_body": None if e.get("body_truncated") else (e.get("body") or "")[:500],
            }
        )
    return out

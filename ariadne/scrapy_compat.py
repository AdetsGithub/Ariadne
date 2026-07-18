"""Helpers for Scrapy ≥2.13 async spider output compatibility."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Any


async def mirror_spider_output(
    sync_process,
    response,
    result: AsyncIterator[Any],
    spider=None,
) -> AsyncIterator[Any]:
    """Buffer an async spider result, run sync process_spider_output, re-yield."""
    buffered: list[Any] = []
    async for o in result:
        buffered.append(o)
    for o in sync_process(response, buffered, spider):
        yield o


def ensure_iterable(result: Iterable[Any] | Any) -> Iterable[Any]:
    if result is None:
        return ()
    return result

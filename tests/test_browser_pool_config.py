"""Network sniffer MAX_BODY_SIZE truncation."""

import pytest

from ariadne.browser.network import endpoints_from_bucket


def test_endpoints_from_bucket_marks_truncated():
    bucket = [
        {
            "url": "https://api.example.com/big.json",
            "method": "GET",
            "status": 200,
            "resource_type": "xhr",
            "content_type": "application/json",
            "headers": {},
            "body": None,
            "body_truncated": True,
            "body_bytes": 50_000_000,
        }
    ]
    eps = endpoints_from_bucket(bucket)
    assert eps[0]["body_truncated"] is True
    assert eps[0]["sample_body"] is None
    assert eps[0]["method"] == "GET"


@pytest.mark.asyncio
async def test_checkout_timeout_vs_execution_timeout_attrs():
    from ariadne.browser import BrowserPool

    pool = BrowserPool(checkout_timeout=60.0, execution_timeout=180.0, pool_size=4)
    assert pool.checkout_timeout == 60.0
    assert pool.execution_timeout == 180.0
    assert pool.checkout_timeout < pool.execution_timeout

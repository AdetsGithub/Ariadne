"""EndpointItem field persistence from apisnoop network bucket."""

from ariadne.browser.network import endpoints_from_bucket
from ariadne.items import EndpointItem


def _endpoint_item_from_bucket_entry(ep: dict) -> EndpointItem:
    """Mirror ApiSnoopSpider field mapping."""
    return EndpointItem(
        url=ep["url"],
        method=ep.get("method"),
        source="network",
        auth_required=None,
        content_type=ep.get("content_type"),
        parameters=ep.get("parameters") or [],
        status=ep.get("status"),
        body_truncated=ep.get("body_truncated", False),
        sample_body=ep.get("sample_body"),
    )


def test_endpoint_item_preserves_body_truncated():
    bucket = [
        {
            "url": "https://api.example.com/big.json",
            "method": "POST",
            "status": 200,
            "resource_type": "xhr",
            "content_type": "application/json",
            "headers": {},
            "body": None,
            "body_truncated": True,
            "body_bytes": 50_000_000,
        }
    ]
    ep = endpoints_from_bucket(bucket)[0]
    item = _endpoint_item_from_bucket_entry(ep)
    assert item["body_truncated"] is True
    assert item["sample_body"] is None
    assert item["status"] == 200


def test_endpoint_item_includes_sample_body_when_not_truncated():
    bucket = [
        {
            "url": "https://api.example.com/small.json",
            "method": "GET",
            "status": 200,
            "resource_type": "fetch",
            "content_type": "application/json",
            "headers": {},
            "body": '{"ok":true}',
            "body_truncated": False,
        }
    ]
    ep = endpoints_from_bucket(bucket)[0]
    item = _endpoint_item_from_bucket_entry(ep)
    assert item["body_truncated"] is False
    assert item["sample_body"] == '{"ok":true}'

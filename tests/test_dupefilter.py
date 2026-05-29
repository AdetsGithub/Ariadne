"""TransportAwareDupeFilter includes mode in fingerprint."""

from scrapy.http import Request

from ariadne.dupefilters import TransportAwareDupeFilter


def test_l1_and_l2_different_fingerprints():
    df = TransportAwareDupeFilter()
    r1 = Request("https://example.com/page", meta={"transport_mode": "L1_impersonate"})
    r2 = Request("https://example.com/page", meta={"transport_mode": "L2_browser"})
    assert df.request_fingerprint(r1) != df.request_fingerprint(r2)


def test_clearance_epoch_changes_fingerprint():
    df = TransportAwareDupeFilter()
    r1 = Request(
        "https://example.com/page",
        meta={"transport_mode": "L1_impersonate", "clearance_epoch": 0},
    )
    r2 = Request(
        "https://example.com/page",
        meta={"transport_mode": "L1_impersonate", "clearance_epoch": 1},
    )
    assert df.request_fingerprint(r1) != df.request_fingerprint(r2)


def test_same_mode_same_fingerprint():
    df = TransportAwareDupeFilter()
    r1 = Request("https://example.com/page", meta={"transport_mode": "L1_impersonate"})
    r2 = Request("https://example.com/page", meta={"transport_mode": "L1_impersonate"})
    assert df.request_fingerprint(r1) == df.request_fingerprint(r2)

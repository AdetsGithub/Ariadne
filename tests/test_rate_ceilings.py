"""Rate ceiling resolution and middleware."""

from scrapy.http import Request

from ariadne.downloadermiddlewares.rate_ceiling import RateCeilingMiddleware
from ariadne.engagement import ConcurrencyConfig, RATE_HARD_CEILINGS, resolve_rate_ceilings


def test_rate_ceilings_clamp_without_force_unsafe():
    conc = ConcurrencyConfig(
        max_concurrent_requests=32,
        max_concurrent_per_domain=16,
        max_rps_per_host=10.0,
    )
    applied, audit = resolve_rate_ceilings(conc, force_unsafe=False)
    assert applied["max_concurrent_requests"] == RATE_HARD_CEILINGS["max_concurrent_requests"]
    assert applied["max_concurrent_per_domain"] == RATE_HARD_CEILINGS["max_concurrent_per_domain"]
    assert applied["max_rps_per_host"] == RATE_HARD_CEILINGS["max_rps_per_host"]
    assert audit is not None
    assert audit["clamped"]


def test_rate_ceilings_allow_with_force_unsafe():
    conc = ConcurrencyConfig(
        max_concurrent_requests=32,
        max_concurrent_per_domain=16,
        max_rps_per_host=10.0,
    )
    applied, audit = resolve_rate_ceilings(conc, force_unsafe=True)
    assert applied["max_concurrent_requests"] == 32
    assert audit is not None
    assert audit["force_unsafe"] is True
    assert "exceeds_ceilings" in audit


def test_rate_ceiling_middleware_sets_download_delay():
    mw = RateCeilingMiddleware(max_rps_per_host=2.0)  # 0.5s min interval
    req = Request("https://example.com/a")
    mw.process_request(req)
    first_delay = req.meta.get("download_delay", 0)
    req2 = Request("https://example.com/b")
    mw.process_request(req2)
    assert req2.meta.get("download_delay", 0) >= 0.4


def test_engagement_settings_maps_per_domain_and_rps():
    from pathlib import Path

    from ariadne.engagement import engagement_to_scrapy_settings, load_engagement

    path = Path(__file__).resolve().parents[1] / "engagements" / "example.yaml"
    cfg = load_engagement(path)
    overrides = engagement_to_scrapy_settings(cfg)
    assert "CONCURRENT_REQUESTS_PER_DOMAIN" in overrides
    assert "ARIADNE_MAX_RPS_PER_HOST" in overrides

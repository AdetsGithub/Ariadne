"""Engagement schema + reactor settings."""

from pathlib import Path

from ariadne import settings as ariadne_settings
from ariadne.engagement import engagement_to_scrapy_settings, load_engagement


def test_reactor_setting_mandatory():
    assert (
        ariadne_settings.TWISTED_REACTOR
        == "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
    )


def test_dupefilter_setting():
    assert ariadne_settings.DUPEFILTER_CLASS == "ariadne.dupefilters.TransportAwareDupeFilter"


def test_load_example_engagement():
    path = Path(__file__).resolve().parents[1] / "engagements" / "example.yaml"
    cfg = load_engagement(path)
    assert cfg.scope.respect_robots == "observe"
    assert cfg.crawl.session.escalation_priority == 100
    overrides = engagement_to_scrapy_settings(cfg)
    assert overrides["ARIADNE_RESPECT_ROBOTS"] == "observe"
    assert overrides["ARIADNE_ESCALATION_PRIORITY"] == 100

"""Engagement YAML schema validation (Pydantic)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class EngagementMeta(BaseModel):
    id: str
    client: str
    operator: str
    authorized_until: datetime | None = None


class ScopeConfig(BaseModel):
    allow_domains: list[str] = Field(default_factory=list)
    allow_url_regex: list[str] = Field(default_factory=list)
    deny_url_regex: list[str] = Field(default_factory=list)
    max_depth: int = 5
    respect_robots: Literal["observe", "obey", "ignore"] = "observe"


class TransportConfig(BaseModel):
    initial_mode: Literal["L0_http", "L1_impersonate", "L2_browser", "L3_unlocker"] = (
        "L1_impersonate"
    )
    escalate_to: list[str] = Field(default_factory=lambda: ["L2_browser"])
    impersonate_profiles: list[str] | None = None


class ConcurrencyConfig(BaseModel):
    max_concurrent_requests: int = 8
    download_delay_mean: float = 3.5
    download_delay_std: float = 1.2


class SessionConfig(BaseModel):
    challenge_lease_ttl_seconds: int = 120
    clearance_wait_delay_mean: float = 2.0
    escalation_priority: int = 100


class BrowserConfig(BaseModel):
    headless: bool = False
    stealth: bool = True
    humanize: bool = True
    capture_network: bool = False
    pool_size: int = 4
    checkout_timeout_seconds: int = 60
    execution_timeout_seconds: float = 180.0
    max_contexts_served: int = 5000
    disable_webrtc: bool = True
    proxy_dns: bool = True


class HoneypotConfig(BaseModel):
    l1_unverified: Literal["defer", "risk_score", "follow"] = "defer"


class ProxiesConfig(BaseModel):
    class_: Literal["datacenter", "residential", "mobile"] = Field(
        default="residential", alias="class"
    )
    sticky_ttl_seconds: int = 600
    urls: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class CaptureConfig(BaseModel):
    screenshots: Literal["never", "on_challenge_or_error", "always"] = "on_challenge_or_error"
    har: Literal["never", "on_apisnoop_or_challenge", "always"] = "on_apisnoop_or_challenge"


class OutputConfig(BaseModel):
    dir: str = "./artifacts"
    formats: list[str] = Field(default_factory=lambda: ["ndjson", "markdown_summary"])
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    redact_pii: bool = True


class CrawlConfig(BaseModel):
    mode: Literal["map", "extract", "apisnoop", "auth", "canary", "passive"] = "map"
    start_urls: list[str]
    transport: TransportConfig = Field(default_factory=TransportConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    honeypot: HoneypotConfig = Field(default_factory=HoneypotConfig)
    proxies: ProxiesConfig = Field(default_factory=ProxiesConfig)


class EngagementConfig(BaseModel):
    engagement: EngagementMeta
    scope: ScopeConfig
    crawl: CrawlConfig
    output: OutputConfig = Field(default_factory=OutputConfig)

    @field_validator("engagement")
    @classmethod
    def _engagement_ok(cls, v: EngagementMeta) -> EngagementMeta:
        if not v.id.strip():
            raise ValueError("engagement.id required")
        return v


def load_engagement(path: str | Path) -> EngagementConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Engagement file must be a YAML mapping")
    return EngagementConfig.model_validate(data)


def engagement_to_scrapy_settings(cfg: EngagementConfig) -> dict[str, Any]:
    """Map engagement YAML into Scrapy/Ariadne settings overrides."""
    out_dir = Path(cfg.output.dir) / cfg.engagement.id
    mode = cfg.crawl.mode
    # Real Playwright pool only when the crawl needs L2 up front.
    # Challenge escalation still uses the L2 stub when the pool is off.
    enable_browser = (
        mode in {"apisnoop", "auth"}
        or cfg.crawl.transport.initial_mode.startswith("L2")
        or cfg.crawl.browser.capture_network
    )
    return {
        "ARIADNE_ENGAGEMENT": cfg.model_dump(mode="json", by_alias=True),
        "ARIADNE_OUTPUT_DIR": str(out_dir),
        "ARIADNE_RESPECT_ROBOTS": cfg.scope.respect_robots,
        "ARIADNE_HONEYPOT_L1_UNVERIFIED": cfg.crawl.honeypot.l1_unverified,
        "ARIADNE_INITIAL_TRANSPORT": cfg.crawl.transport.initial_mode,
        "ARIADNE_ESCALATION_PRIORITY": cfg.crawl.session.escalation_priority,
        "ARIADNE_CHALLENGE_LEASE_TTL": cfg.crawl.session.challenge_lease_ttl_seconds,
        "ARIADNE_CLEARANCE_WAIT_DELAY": cfg.crawl.session.clearance_wait_delay_mean,
        "ARIADNE_IMPERSONATE_PROFILES": cfg.crawl.transport.impersonate_profiles,
        "ARIADNE_PROXY_LIST": cfg.crawl.proxies.urls or None,
        "CONCURRENT_REQUESTS": cfg.crawl.concurrency.max_concurrent_requests,
        "DOWNLOAD_DELAY": cfg.crawl.concurrency.download_delay_mean,
        "ARIADNE_BROWSER_POOL_ENABLED": enable_browser,
        "ARIADNE_BROWSER_POOL_SIZE": cfg.crawl.browser.pool_size,
        "ARIADNE_BROWSER_CHECKOUT_TIMEOUT": float(cfg.crawl.browser.checkout_timeout_seconds),
        "ARIADNE_BROWSER_EXECUTION_TIMEOUT": float(cfg.crawl.browser.execution_timeout_seconds),
        "ARIADNE_BROWSER_MAX_CONTEXTS_SERVED": cfg.crawl.browser.max_contexts_served,
        "ARIADNE_BROWSER_HEADLESS": cfg.crawl.browser.headless,
        "ARIADNE_CAPTURE_NETWORK": mode == "apisnoop" or cfg.crawl.browser.capture_network,
        "ARIADNE_SCREENSHOT_MODE": cfg.output.capture.screenshots,
    }

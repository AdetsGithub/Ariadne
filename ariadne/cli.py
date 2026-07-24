"""Ariadne CLI."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from ariadne import __version__
from ariadne.engagement import engagement_to_scrapy_settings, load_engagement
from ariadne.stealth import list_impersonate_profiles, load_profile_catalog

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Ariadne security testing crawler")


@app.command()
def version() -> None:
    """Print package version."""
    typer.echo(__version__)


@app.command("validate")
def validate_engagement(config: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Validate an engagement YAML file."""
    cfg = load_engagement(config)
    typer.echo(f"OK: engagement {cfg.engagement.id} ({cfg.crawl.mode}), robots={cfg.scope.respect_robots}")


@app.command("init")
def init_engagement(
    path: Path = typer.Argument(Path("engagement.yaml")),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Write a starter engagement YAML."""
    if path.exists() and not force:
        typer.echo(f"{path} exists; use --force to overwrite", err=True)
        raise typer.Exit(1)
    sample = Path(__file__).resolve().parents[1] / "engagements" / "example.yaml"
    if sample.exists():
        path.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        path.write_text(_DEFAULT_ENGAGEMENT, encoding="utf-8")
    typer.echo(f"Wrote {path}")


@app.command()
def doctor(
    leak_check: bool = typer.Option(False, "--leak-check", help="Verify WebRTC-disabled launch args / DNS guidance"),
) -> None:
    """Check reactor setting, profile catalog, curl_cffi, and optional Playwright TLS anchor."""
    from ariadne import settings as ariadne_settings

    reactor = getattr(ariadne_settings, "TWISTED_REACTOR", None)
    ok = reactor == "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
    typer.echo(f"TWISTED_REACTOR: {reactor} {'OK' if ok else 'FAIL'}")
    if not ok:
        raise typer.Exit(2)

    catalog = load_profile_catalog()
    typer.echo(f"Profile catalog: {len(catalog)} entries ({', '.join(sorted(catalog))})")

    try:
        import curl_cffi

        typer.echo(f"curl_cffi: {getattr(curl_cffi, '__version__', 'unknown')}")
        for p in list_impersonate_profiles():
            typer.echo(
                f"  persona ok: {p.profile_id} -> {p.impersonate} "
                f"(chromium_major={p.chromium_major}, l2={p.l2_compatible})"
            )
    except Exception as exc:
        typer.echo(f"curl_cffi check failed: {exc}", err=True)
        raise typer.Exit(2)

    dupe = getattr(ariadne_settings, "DUPEFILTER_CLASS", "")
    typer.echo(f"DUPEFILTER_CLASS: {dupe}")

    try:
        from ariadne.stealth.chromium import detect_playwright_chromium_major

        major = detect_playwright_chromium_major()
        if major is None:
            typer.echo("Playwright Chromium: not installed (L1-only; pip install 'ariadne[browser]')")
        else:
            typer.echo(f"Playwright Chromium major (TLS anchor): {major}")
            anchored = list_impersonate_profiles(chromium_major=major, require_l2_anchor=True)
            typer.echo(f"  L1↔L2 compatible profiles: {[p.profile_id for p in anchored]}")
    except Exception as exc:
        typer.echo(f"Playwright anchor check: {exc}", err=True)

    if leak_check:
        from ariadne.browser import BrowserPool

        pool = BrowserPool(disable_webrtc=True, proxy_dns=True)
        args = " ".join(pool._launch_args())
        if "--disable-webrtc" not in args:
            typer.echo("leak-check FAIL: WebRTC not disabled in launch args", err=True)
            raise typer.Exit(2)
        typer.echo("leak-check: WebRTC disabled in BrowserPool launch args OK")
        typer.echo("leak-check: use SOCKS5h / provider remote-DNS proxies for DNS-via-proxy")
    typer.echo("doctor: OK")


@app.command()
def crawl(
    config: Path = typer.Option(..., "-c", "--config", exists=True, dir_okay=False),
    spider: Optional[str] = typer.Option(
        None, "--spider", help="map|extract|apisnoop (default from YAML mode)"
    ),
    force_unsafe: bool = typer.Option(
        False,
        "--force-unsafe",
        help="Allow rate limits above hard product ceilings (audit logged)",
    ),
) -> None:
    """Run a crawl from an engagement YAML."""
    cfg = load_engagement(config)
    mode_map = {"map": "map", "extract": "extract", "apisnoop": "apisnoop", "auth": "map", "passive": "map"}
    mode = spider or mode_map.get(cfg.crawl.mode, "map")
    settings_overrides = engagement_to_scrapy_settings(cfg, force_unsafe=force_unsafe)

    rate_audit = settings_overrides.pop("ARIADNE_RATE_CEILING_AUDIT", None)
    if rate_audit:
        if rate_audit.get("clamped"):
            typer.echo(
                f"WARNING: rate ceilings clamped to product limits: {rate_audit['clamped']}",
                err=True,
            )
        if force_unsafe:
            out_dir = Path(settings_overrides["ARIADNE_OUTPUT_DIR"])
            _append_force_unsafe_audit(out_dir, cfg, rate_audit)

    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    # Ensure our settings module is used
    import os

    os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "ariadne.settings")
    settings = get_project_settings()
    for k, v in settings_overrides.items():
        settings.set(k, v, priority="cmdline")

    process = CrawlerProcess(settings)
    process.crawl(mode)
    process.start()


@app.command()
def report(
    artifacts: Path = typer.Argument(..., exists=True, file_okay=False),
    sitemap: bool = typer.Option(
        False,
        "--sitemap",
        help="Also write sitemap.jsonl + sitemap.md (union of discovery artifacts)",
    ),
) -> None:
    """Emit a short Markdown summary from NDJSON artifacts."""
    pages = artifacts / "PageItem.ndjson"
    robots = artifacts / "RobotsHintItem.ndjson"
    forms = artifacts / "FormItem.ndjson"
    failed = artifacts / "FailedUrlItem.ndjson"
    outbound = artifacts / "OutboundLinkItem.ndjson"
    assets = artifacts / "AssetItem.ndjson"
    candidates = artifacts / "UrlCandidateItem.ndjson"

    def _count(p: Path) -> int:
        return sum(1 for _ in p.open()) if p.exists() else 0

    n_pages = _count(pages)
    n_robots = _count(robots)
    n_forms = _count(forms)
    n_failed = _count(failed)
    n_outbound = _count(outbound)
    n_assets = _count(assets)
    n_candidates = _count(candidates)
    eng = {}
    eng_path = artifacts / "engagement.json"
    if eng_path.exists():
        eng = json.loads(eng_path.read_text(encoding="utf-8"))
    meta = eng.get("engagement") or {}
    md = f"""# Ariadne report

- Engagement: `{meta.get('id', artifacts.name)}`
- Client: {meta.get('client', 'n/a')}
- Pages: {n_pages}
- Forms: {n_forms}
- Robots hints: {n_robots}
- Assets: {n_assets}
- URL candidates: {n_candidates}
- Failed URLs: {n_failed}
- Outbound links: {n_outbound}

Artifacts: `{artifacts}`
"""
    out = artifacts / "summary.md"
    out.write_text(md, encoding="utf-8")
    typer.echo(md)
    typer.echo(f"Wrote {out}")

    if sitemap:
        from ariadne.reporting.sitemap import write_sitemap_report

        jsonl, sm_md, counts = write_sitemap_report(artifacts)
        typer.echo(f"Sitemap union: {sum(counts.values())} unique URLs → {jsonl}")
        typer.echo(f"Wrote {sm_md}")


@app.command()
def pack(
    artifacts: Path = typer.Argument(..., exists=True, file_okay=False),
    encrypt: bool = typer.Option(False, "--encrypt", help="Encrypt the zip with recipient pubkey"),
    pubkey: Optional[Path] = typer.Option(
        None,
        "--pubkey",
        exists=True,
        dir_okay=False,
        help="Recipient public key file (age1… or ASCII-armored PGP). Required with --encrypt.",
    ),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Encrypted output path"),
) -> None:
    """Zip engagement artifacts; optionally encrypt with an explicit pubkey (no GPG keyring)."""
    from ariadne.reporting.pack import PackError, pack_artifacts

    try:
        result = pack_artifacts(artifacts, encrypt=encrypt, pubkey=pubkey, output=output)
    except PackError as exc:
        typer.echo(f"pack failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"Wrote {result}")


def _append_force_unsafe_audit(out_dir: Path, cfg, audit: dict) -> None:
    """Append one JSON line when --force-unsafe is used (SPEC §2.3)."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engagement_id": cfg.engagement.id,
        "operator": cfg.engagement.operator,
        **audit,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "force_unsafe_audit.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
    typer.echo(f"force-unsafe audit: {path}", err=True)


_DEFAULT_ENGAGEMENT = """engagement:
  id: "EXAMPLE-001"
  client: "Example Corp"
  operator: "redteam@example.com"

scope:
  allow_domains:
    - "example.com"
  allow_url_regex:
    - "^https://example\\\\.com/.*"
  max_depth: 2
  respect_robots: observe

crawl:
  mode: map
  start_urls:
    - "https://example.com/"
  transport:
    initial_mode: L1_impersonate
    escalate_to: [L2_browser]
  concurrency:
    max_concurrent_requests: 4
    download_delay_mean: 1.0
  session:
    escalation_priority: 100
  honeypot:
    l1_unverified: defer

output:
  dir: "./artifacts"
  formats: [ndjson, markdown_summary]
"""


if __name__ == "__main__":
    app()

"""OPSEC leak-check helpers for doctor --leak-check (SPEC AC15 / §7.3)."""

from __future__ import annotations

import ipaddress
import re
from typing import Iterable
from urllib.parse import urlparse

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def extract_ipv4(text: str) -> set[str]:
    """Return plausible IPv4 literals from text."""
    found: set[str] = set()
    for match in _IP_RE.findall(text or ""):
        try:
            ipaddress.IPv4Address(match)
        except ipaddress.AddressValueError:
            continue
        found.add(match)
    return found


def proxy_scheme(proxy_url: str) -> str:
    return urlparse(proxy_url).scheme.lower()


def dns_via_proxy_enforced(proxy_url: str) -> bool:
    """True when proxy URL scheme forces remote DNS (socks5h)."""
    return proxy_scheme(proxy_url) in {"socks5", "socks5h"}


def host_ips_in_ice_candidates(candidates: Iterable[str], host_ips: set[str]) -> set[str]:
    """Return host IPs observed in WebRTC ICE candidate strings."""
    leaks: set[str] = set()
    for candidate in candidates:
        for ip in host_ips:
            if ip in candidate:
                leaks.add(ip)
    return leaks


def normalize_echo_ip(body: str) -> str | None:
    """First IPv4 token from a plain-text echo response."""
    ips = extract_ipv4(body.strip())
    return next(iter(ips), None)


async def fetch_echo_ip(echo_url: str, *, proxy_url: str | None = None) -> str | None:
    """GET a plain-text IP echo service; optional proxy."""
    from curl_cffi.requests import AsyncSession

    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}
    async with AsyncSession() as session:
        resp = await session.get(echo_url, timeout=15, proxies=proxies)
        return normalize_echo_ip(resp.text)


async def collect_ice_candidates(proxy_url: str, launch_args: list[str]) -> list[str]:
    """Gather ICE candidate strings through a proxied Playwright browser."""
    from playwright.async_api import async_playwright

    script = """
    () => new Promise((resolve) => {
      const pc = new RTCPeerConnection({iceServers: [{urls: 'stun:stun.l.google.com:19302'}]});
      const out = [];
      pc.onicecandidate = (e) => {
        if (e.candidate) out.push(e.candidate.candidate);
        else resolve(out);
      };
      pc.createDataChannel('leakcheck');
      pc.createOffer().then((o) => pc.setLocalDescription(o));
      setTimeout(() => resolve(out), 3000);
    })
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=launch_args,
            proxy={"server": proxy_url},
        )
        try:
            page = await browser.new_page()
            result = await page.evaluate(script)
            return list(result or [])
        finally:
            await browser.close()


async def run_live_leak_check(
    proxy_url: str,
    echo_url: str,
    launch_args: list[str],
) -> list[str]:
    """Run live OPSEC probes; return human-readable failure messages."""
    errors: list[str] = []
    if not dns_via_proxy_enforced(proxy_url):
        errors.append(
            f"proxy scheme {proxy_scheme(proxy_url)!r} is not socks5/socks5h — DNS may leak host resolver"
        )

    try:
        host_ip = await fetch_echo_ip(echo_url, proxy_url=None)
        proxy_ip = await fetch_echo_ip(echo_url, proxy_url=proxy_url)
    except Exception as exc:
        errors.append(f"echo probe failed: {exc}")
        return errors

    if host_ip and proxy_ip and host_ip == proxy_ip:
        errors.append(
            f"exit IP via proxy ({proxy_ip}) matches direct host echo ({host_ip}) — proxy may not isolate traffic"
        )

    if host_ip:
        try:
            candidates = await collect_ice_candidates(proxy_url, launch_args)
            leaked = host_ips_in_ice_candidates(candidates, {host_ip})
            if leaked:
                errors.append(f"host IP {host_ip} observed in ICE candidates: {sorted(leaked)}")
        except Exception as exc:
            errors.append(f"WebRTC ICE probe failed: {exc}")

    return errors


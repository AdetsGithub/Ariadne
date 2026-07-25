"""doctor --leak-check helper unit tests (no live network)."""

from ariadne.opsec.leak_check import (
    dns_via_proxy_enforced,
    extract_ipv4,
    host_ips_in_ice_candidates,
    normalize_echo_ip,
    proxy_scheme,
)


def test_extract_ipv4_from_echo_body():
    assert extract_ipv4("Your IP is 203.0.113.10\n") == {"203.0.113.10"}


def test_normalize_echo_ip():
    assert normalize_echo_ip("203.0.113.10") == "203.0.113.10"
    assert normalize_echo_ip("no ip here") is None


def test_dns_via_proxy_enforced_socks5h():
    assert dns_via_proxy_enforced("socks5h://user:pass@proxy:1080") is True
    assert dns_via_proxy_enforced("http://user:pass@proxy:8080") is False


def test_proxy_scheme():
    assert proxy_scheme("socks5h://127.0.0.1:1080") == "socks5h"


def test_host_ips_in_ice_candidates_detects_leak():
    candidates = [
        "candidate:1 1 UDP 2130706431 203.0.113.10 54321 typ host",
        "candidate:2 1 UDP 1694498815 198.51.100.2 54322 typ srflx",
    ]
    leaks = host_ips_in_ice_candidates(candidates, {"203.0.113.10"})
    assert leaks == {"203.0.113.10"}


def test_host_ips_in_ice_candidates_clean():
    candidates = ["candidate:2 1 UDP 1694498815 198.51.100.2 54322 typ srflx"]
    assert not host_ips_in_ice_candidates(candidates, {"203.0.113.10"})

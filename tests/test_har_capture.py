"""Conditional HAR capture wiring."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ariadne.browser.har import build_har_path, har_capture_enabled


def test_har_capture_enabled_for_apisnoop_network():
    settings = {"ARIADNE_HAR_MODE": "on_apisnoop_or_challenge", "ARIADNE_CAPTURE_NETWORK": True}
    assert har_capture_enabled(settings) is True


def test_har_capture_disabled_when_never():
    settings = {"ARIADNE_HAR_MODE": "never", "ARIADNE_CAPTURE_NETWORK": True}
    assert har_capture_enabled(settings) is False


def test_har_capture_always():
    settings = {"ARIADNE_HAR_MODE": "always", "ARIADNE_CAPTURE_NETWORK": False}
    assert har_capture_enabled(settings) is True


def test_build_har_path_under_output_har(tmp_path):
    path = build_har_path(str(tmp_path), "host:example.com", "https://example.com/page")
    assert path.parent.name == "har"
    assert path.suffix == ".har"
    assert "host_example.com" in path.name


@pytest.mark.asyncio
async def test_checkout_passes_record_har_path():
    from ariadne.browser import BrowserPool, BrowserProcess

    pool = BrowserPool(pool_size=1, checkout_timeout=5.0, execution_timeout=10.0)
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_context.close = AsyncMock()

    bp = BrowserProcess(browser_id="b0", browser=mock_browser, contexts_served=0)
    pool._browsers = [bp]
    pool._playwright = MagicMock()
    pool._semaphore = __import__("asyncio").Semaphore(1)
    pool._closed = False

    har = "/tmp/out/har/session_abc123.har"
    async with pool.checkout(
        "host:example.com",
        persona={"user_agent": "test", "viewport": {"width": 800, "height": 600}},
        record_har_path=har,
    ) as ctx:
        assert ctx is mock_context

    mock_browser.new_context.assert_awaited_once()
    kwargs = mock_browser.new_context.await_args.kwargs
    assert kwargs["record_har_path"] == har
    assert kwargs["record_har_content"] == "omit"

"""Conditional HAR capture for apisnoop / challenge evidence (SPEC AC17)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _settings_bool(settings: Any, key: str, default: bool = False) -> bool:
    val = settings.get(key, default)
    if hasattr(settings, "getbool"):
        return bool(settings.getbool(key, default))
    return bool(val)


def har_capture_enabled(settings: Any) -> bool:
    """True when this engagement should record Playwright HAR files."""
    mode = settings.get("ARIADNE_HAR_MODE", "on_apisnoop_or_challenge")
    if mode == "never":
        return False
    if mode == "always":
        return True
    # on_apisnoop_or_challenge — apisnoop enables network capture
    return _settings_bool(settings, "ARIADNE_CAPTURE_NETWORK", False)


def build_har_path(output_dir: str, session_id: str, url: str) -> Path:
    """Deterministic HAR path under {output}/har/."""
    safe_sid = session_id.replace(":", "_").replace("/", "_")
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    har_dir = Path(output_dir) / "har"
    har_dir.mkdir(parents=True, exist_ok=True)
    return har_dir / f"{safe_sid}_{url_hash}.har"

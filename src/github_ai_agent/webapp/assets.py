from __future__ import annotations

from pathlib import Path

WEB_ASSET_DIR = Path(__file__).resolve().parent.parent / "web_assets"


def read_web_asset(name: str) -> str:
    return (WEB_ASSET_DIR / name).read_text(encoding="utf-8")


ONBOARDING_HTML = read_web_asset("onboarding.html")
APP_HTML = read_web_asset("app.html")
ASSET_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}

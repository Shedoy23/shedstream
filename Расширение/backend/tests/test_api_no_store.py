"""Regression: authenticated API state must never be browser-cached."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_CHANNEL_NAME", "test_channel")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")


async def main() -> int:
    from starlette.responses import Response
    from main import security_headers

    async def next_response(_request):
        return Response("ok")

    api_request = SimpleNamespace(url=SimpleNamespace(path="/api/viewer/stats/alice"))
    api_response = await security_headers(api_request, next_response)
    assert api_response.headers["cache-control"] == "no-store, max-age=0"
    assert api_response.headers["pragma"] == "no-cache"
    assert api_response.headers["expires"] == "0"

    static_request = SimpleNamespace(url=SimpleNamespace(path="/viewer.js"))
    static_response = await security_headers(static_request, next_response)
    assert "cache-control" not in static_response.headers

    frontend = (BACKEND.parent / "frontend" / "viewer.js").read_text(encoding="utf-8")
    for endpoint in ("/api/viewer/perks", "/api/viewer/stats/${userLogin}"):
        start = frontend.index(f"fetch(`${{API_URL}}{endpoint}")
        fetch_block = frontend[start: start + 700]
        assert "cache: 'no-store'" in fetch_block, endpoint

    print("PASS: API responses are no-store and critical viewer fetches bypass old cache")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

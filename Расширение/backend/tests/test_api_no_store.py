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


SECURITY = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "strict-transport-security": "max-age=63072000; includeSubDomains",
    "content-security-policy": "frame-ancestors https://*.twitch.tv https://*.ext-twitch.tv",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


def assert_security(headers, where):
    for name, value in SECURITY.items():
        assert headers.get(name) == value, f"{where}: {name}={headers.get(name)!r}"


async def main() -> int:
    # 25.09.2026: заголовки ставит чистый ASGI-мидлварь (быстрее
    # BaseHTTPMiddleware). Проверяем через всё приложение, как их увидит браузер.
    import httpx
    from main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        api = await client.get("/api/zz-header-probe")
        assert_security(api.headers, "api")
        assert api.headers["cache-control"] == "no-store, max-age=0"
        assert api.headers["pragma"] == "no-cache"
        assert api.headers["expires"] == "0"

        static = await client.get("/zz-static-probe.js")
        assert_security(static.headers, "static")
        assert "cache-control" not in static.headers, static.headers.get("cache-control")

        preflight = await client.options("/api/bannerlord/battle-status", headers={
            "Origin": "https://abc123.ext-twitch.tv",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-twitch-jwt",
        })
        assert preflight.status_code == 200, preflight.status_code
        assert preflight.headers.get("access-control-allow-origin") == "https://abc123.ext-twitch.tv"
        assert_security(preflight.headers, "preflight")

    frontend = (BACKEND.parent / "frontend" / "viewer.js").read_text(encoding="utf-8")
    for endpoint in ("/api/viewer/perks", "/api/viewer/stats/${userLogin}"):
        start = frontend.index(f"fetch(`${{API_URL}}{endpoint}")
        fetch_block = frontend[start: start + 700]
        assert "cache: 'no-store'" in fetch_block, endpoint

    print("PASS: API responses are no-store and critical viewer fetches bypass old cache")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

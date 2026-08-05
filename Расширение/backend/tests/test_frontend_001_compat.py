"""Regression coverage for the already published frontend 0.0.1.

Standalone: python tests/test_frontend_001_compat.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import pathlib
import sys
import time

import jwt
from starlette.requests import Request


BACKEND = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test-client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test-secret")
os.environ.setdefault("TWITCH_BOT_ID", "1")
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")
TEST_SECRET = b"compat-test-extension-secret-32bytes"
os.environ.setdefault(
    "TWITCH_EXTENSION_SECRET", base64.b64encode(TEST_SECRET).decode("ascii")
)


failures: list[str] = []


def check(condition: bool, label: str) -> None:
    mark = "OK" if condition else "FAIL"
    print(f"  {mark:4} {label}")
    if not condition:
        failures.append(label)


def json_request(path: str, payload: dict) -> Request:
    body = json.dumps(payload).encode("utf-8")
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 443),
        },
        receive,
    )


async def main() -> int:
    from routes.compat import legacy_event_status, router as compat_router
    from routes import misc

    print("[1] Published 0.0.1 event-status contract")
    expected = {
        "pool": 0,
        "pool_pct_points": 0,
        "min_points": 0,
        "can_start": False,
        "can_start_reason": "feature_removed",
        "top_contributors": [],
        "active_event": None,
        "last_winner": None,
    }
    check(await legacy_event_status() == expected, "legacy GET returns the exact inert shape")
    paths = {(route.path, tuple(route.methods or ())) for route in compat_router.routes}
    check(any(path == "/api/event/status" and "GET" in methods for path, methods in paths),
          "read-only legacy status route exists")
    check(not any(path in {"/api/event/contribute", "/api/event/bid"} for path, _ in paths),
          "removed currency mutation routes stay absent")

    print("[2] Twitch identity resolver cannot use client-supplied numeric IDs")
    secret = TEST_SECRET
    previous_secret = os.environ.get("TWITCH_EXTENSION_SECRET")
    previous_cache = dict(misc._twitch_id_cache)
    os.environ["TWITCH_EXTENSION_SECRET"] = base64.b64encode(secret).decode("ascii")
    misc._twitch_id_cache.clear()
    misc._twitch_id_cache["123456"] = "victim_login"
    try:
        result = await misc.resolve_twitch_token(json_request(
            "/api/user/resolve-twitch-token", {"opaque_id": "123456"}
        ))
        check(result.get("login") is None, "unsigned numeric opaque_id cannot read cached identity")

        result = await misc.resolve_twitch_token(json_request(
            "/api/user/resolve-twitch-token",
            {"token": "invalid", "opaque_id": "123456"},
        ))
        check(result.get("login") is None, "invalid JWT cannot fall back to numeric opaque_id")

        token = jwt.encode(
            {
                "exp": int(time.time()) + 300,
                "user_id": "123456",
                "opaque_user_id": "Uverified",
                "channel_id": "98319857",
                "role": "viewer",
            },
            secret,
            algorithm="HS256",
        )
        result = await misc.resolve_twitch_token(json_request(
            "/api/user/resolve-twitch-token",
            {"token": token, "opaque_id": "Uverified", "user_id": "999999"},
        ))
        check(result.get("login") == "victim_login", "valid 0.0.1/0.0.2 JWT path still resolves")
        check(misc._twitch_id_cache.get("Uverified") == "victim_login",
              "signed opaque alias is cached for the same viewer")

        misc._twitch_id_cache.pop("attacker-alias", None)
        result = await misc.resolve_twitch_token(json_request(
            "/api/user/resolve-twitch-token",
            {"token": token, "opaque_id": "attacker-alias"},
        ))
        check(result.get("login") == "victim_login", "mismatched alias does not break normal resolution")
        check("attacker-alias" not in misc._twitch_id_cache,
              "mismatched client alias is never trusted or cached")
    finally:
        misc._twitch_id_cache.clear()
        misc._twitch_id_cache.update(previous_cache)
        if previous_secret is None:
            os.environ.pop("TWITCH_EXTENSION_SECRET", None)
        else:
            os.environ["TWITCH_EXTENSION_SECRET"] = previous_secret

    print("-" * 64)
    if failures:
        print(f"FAILED: {len(failures)}")
        return 1
    print("ALL GREEN: published 0.0.1 remains supported without reopening legacy writes")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

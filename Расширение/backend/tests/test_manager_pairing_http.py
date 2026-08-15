"""HTTP boundary for Manager create → browser approve → one-time exchange."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from starlette.requests import Request

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")
os.environ["MANAGER_CREDENTIAL_PEPPER"] = "test-manager-pepper-at-least-32-characters"
os.environ["MANAGER_PUBLIC_BASE_URL"] = "https://testserver"

CHANNEL_ID = 98319857


def request(method: str, path: str, body: bytes = b"", query: str = "", content_type: str = ""):
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    headers = []
    if content_type:
        headers.append((b"content-type", content_type.encode("ascii")))
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query.encode("ascii"),
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }, receive)


def json_request(path: str, payload: dict) -> Request:
    return request(
        "POST", path, json.dumps(payload).encode("utf-8"),
        content_type="application/json",
    )


def form_request(path: str, payload: dict) -> Request:
    return request(
        "POST", path, urlencode(payload).encode("utf-8"),
        content_type="application/x-www-form-urlencoded",
    )


def payload(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


async def main() -> int:
    import dependencies
    import manager_auth
    from database import Database
    from migrations import m110_manager_credentials
    from modules._loader import discover_modules
    from routes import manager as routes
    from routes import streamer

    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_manager_http_")
    os.close(fd)
    os.unlink(db_path)
    db = Database(db_path)
    original_cookie = routes._read_session_cookie
    original_rate = routes.check_rate_limit
    try:
        await db.init_tables()
        async with db._connect() as conn:
            await m110_manager_credentials.apply(conn)
            columns = await (await conn.execute("PRAGMA table_info(channels)")).fetchall()
            if "approved" not in {row[1] for row in columns}:
                await conn.execute(
                    "ALTER TABLE channels ADD COLUMN approved INTEGER NOT NULL DEFAULT 0"
                )
            await conn.execute(
                "INSERT INTO channels (channel_id,login,display_name,tier,approved) "
                "VALUES (?, 'alice', 'Alice', 'free', 1)", (CHANNEL_ID,)
            )
            await conn.commit()
        dependencies.set_db(db)
        discover_modules()

        safe_return = "/manager/pair?code=ABCD-EFGH"
        assert streamer._safe_return_to(safe_return) == safe_return
        assert streamer._safe_return_to("https://evil.example/") is None
        state = streamer._issue_state(safe_return)
        assert streamer._consume_state(state) == (True, safe_return)
        assert streamer._consume_state(state) == (False, None)

        secret = "manager-http-device-secret-with-32-plus-characters"
        create = await routes.manager_pairing_create(json_request(
            "/v1/manager/pairings",
            {
                "installation_id": "installation-http-0001",
                "module_id": "rimworld",
                "device_challenge": manager_auth.device_challenge(secret),
            },
        ))
        assert create.status_code == 200, create.body
        created = payload(create)
        assert created["verification_uri"].startswith("https://testserver/manager/pair?code=")
        assert "device_secret" not in created

        routes._read_session_cookie = lambda _request: None
        unauthenticated = await routes.manager_pair_page(request(
            "GET", "/manager/pair", query="code=" + created["user_code"]
        ))
        assert unauthenticated.status_code == 401
        assert "return_to=" in unauthenticated.body.decode("utf-8")

        routes._read_session_cookie = lambda _request: CHANNEL_ID
        page = await routes.manager_pair_page(request(
            "GET", "/manager/pair", query="code=" + created["user_code"]
        ))
        assert page.status_code == 200
        page_text = page.body.decode("utf-8")
        match = re.search(r"name='csrf' value='([^']+)'", page_text)
        assert match, page_text
        csrf = match.group(1)
        assert "no-store" in page.headers.get("cache-control", "")

        bad_csrf = await routes.manager_pair_decide(form_request(
            "/manager/pair",
            {"pairing_id": created["pairing_id"], "csrf": "bad", "decision": "approve"},
        ))
        assert bad_csrf.status_code == 400

        approved = await routes.manager_pair_decide(form_request(
            "/manager/pair",
            {"pairing_id": created["pairing_id"], "csrf": csrf, "decision": "approve"},
        ))
        assert approved.status_code == 200

        wrong = await routes.manager_pairing_exchange(
            created["pairing_id"],
            json_request("/exchange", {"device_secret": "wrong-secret"}),
        )
        assert wrong.status_code == 401

        exchanged = await routes.manager_pairing_exchange(
            created["pairing_id"],
            json_request("/exchange", {"device_secret": secret}),
        )
        assert exchanged.status_code == 200
        exchanged_body = payload(exchanged)
        assert exchanged_body["channel_id"] == CHANNEL_ID
        assert exchanged_body["module_id"] == "rimworld"
        assert exchanged_body["access_token"].startswith("slmgr_v1.")

        duplicate = await routes.manager_pairing_exchange(
            created["pairing_id"],
            json_request("/exchange", {"device_secret": secret}),
        )
        assert duplicate.status_code == 409

        routes.check_rate_limit = lambda *_args, **_kwargs: False
        limited = await routes.manager_pairing_create(json_request(
            "/v1/manager/pairings", {}
        ))
        assert limited.status_code == 429
        routes.check_rate_limit = original_rate

        oversized = await routes.manager_pairing_create(request(
            "POST", "/v1/manager/pairings", b"{" + b"x" * 9000,
            content_type="application/json",
        ))
        assert oversized.status_code == 400
        assert payload(oversized)["status"] == "request_too_large"

        route_paths = {(route.path, tuple(route.methods or ())) for route in routes.router.routes}
        assert ("/v1/manager/pairings", ("POST",)) in route_paths
        assert any(path == "/manager/pair" and "POST" in methods for path, methods in route_paths)
    finally:
        routes._read_session_cookie = original_cookie
        routes.check_rate_limit = original_rate
        if getattr(db, "_pool", None):
            await db._pool.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass

    print("ALL GREEN — Manager HTTP pairing is explicit, CSRF-protected and one-time.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

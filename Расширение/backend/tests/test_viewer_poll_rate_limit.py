"""Standalone regression: normal viewers must not exhaust one channel bucket."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_frozen_client_0_0_5  # isolated test environment defaults
import dependencies as d
from fastapi import HTTPException
from starlette.requests import Request


def request(method="GET", path="/api/bannerlord/status"):
    return Request({"type": "http", "method": method, "path": path,
                    "headers": [], "query_string": b"username=spoofed"})


def run():
    d._channel_rate_buckets.clear()
    d._channel_tier_cache.clear()
    with patch.object(d, "verify_twitch_jwt") as verify, \
         patch.object(d, "resolve_jwt_login", return_value="alice"), \
         patch.object(d, "is_channel_registered", return_value=True), \
         patch.object(d, "is_channel_approved", return_value=True), \
         patch.object(d._time, "time", return_value=1000) as clock, \
         patch.dict(d.RATE_LIMITS_BY_TIER, {"free": 300}):
        def viewer(uid, channel=98319857):
            verify.return_value = {"status": "valid", "user_id": str(uid),
                                   "username": "U" + str(uid), "channel_id": str(channel)}

        for uid in range(50):
            viewer(uid)
            for _ in range(150):  # 104 BL polls + shell requests and startup headroom
                d.require_jwt_user(request())
        print("OK: 50 viewers x 150 reads/min in one free channel")
        viewer(0)
        for _ in range(150):
            d.require_jwt_channel(request())
        try:
            d.require_jwt_channel(request())
        except HTTPException as exc:
            assert exc.status_code == 429
            assert int(exc.headers["Retry-After"]) == 60
        else:
            raise AssertionError("one viewer can exceed the read quota")
        viewer(51)
        req = request()
        for _ in range(350):
            d.require_jwt_user(req)
            d.require_jwt_channel(req)
        print("OK: both auth helpers charge the same request only once")
        viewer(0, 22)
        d.require_jwt_channel(request())
        for uid in range(400):
            viewer(uid, 33)
            d.require_jwt_user(request("POST", "/api/viewer/online"))
            d.require_jwt_user(request("POST", "/api/viewer/activity"))
        print("OK: automatic presence reports scale with viewers")
        viewer(0)
        for uid in range(300):
            viewer(uid)
            d.require_jwt_user(request("POST"))
        try:
            d.require_jwt_user(request("POST"))
        except HTTPException as exc:
            assert exc.status_code == 429
            assert exc.detail["status"] == "channel_rate_limited"
        else:
            raise AssertionError("shared write quota bypassed")
        viewer(500)
        d.require_jwt_channel(request())
        clock.return_value = 1060
        viewer(0)
        d.require_jwt_user(request())
        d.require_jwt_user(request("POST"))
        print("OK: writes bounded; reads and channels isolated; window resets")


if __name__ == "__main__":
    run()

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
        d._channel_rate_buckets.clear()
        verify.return_value = {"status": "valid", "username": "Uanonymous", "channel_id": "55"}
        for _ in range(300):
            d.require_jwt_channel(request())
        # Change the query string, never the signed identity: still limited.
        try:
            d.require_jwt_channel(request(path="/api/bannerlord/shop"))
        except HTTPException as exc:
            assert exc.status_code == 429
            assert exc.detail["scope"] == "viewer_poll"
        else:
            raise AssertionError("opaque viewer bypassed quota using another route")
        verify.return_value = {"status": "valid", "channel_id": "55"}
        for _ in range(300):
            d.require_jwt_channel(request())
        try:
            d.require_jwt_channel(request())
        except HTTPException as exc:
            assert exc.status_code == 429
            assert exc.detail["scope"] == "channel"
        else:
            raise AssertionError("missing identity bypassed quota")
        before = {k: dict(v) for k, v in d._channel_rate_buckets.items()}
        verify.return_value = {"status": "invalid"}
        assert d.require_jwt_channel(request()) is None
        assert d.require_jwt_user(request()) is None
        assert d._channel_rate_buckets == before
        print("OK: opaque identity limited; missing identity fails bounded; invalid JWT not charged")
        with patch.object(d, "_CHANNEL_POLL_BUCKETS_MAX", len(before)):
            viewer(999, 55)
            try:
                d.require_jwt_channel(request())
            except HTTPException as exc:
                assert exc.status_code == 429
                assert exc.detail["scope"] == "channel"
            else:
                raise AssertionError("full polling cache bypassed shared fallback limit")
            assert d._channel_rate_buckets.keys() == before.keys()
        print("OK: full polling cache stays bounded and fails into shared quota")


if __name__ == "__main__":
    run()

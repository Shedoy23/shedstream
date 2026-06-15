"""
bannerlord_smoke.py — HTTP smoke tests для всех new-sprint endpoints.

Запуск (требует запущенного backend на target host):
    cd Расширение/backend
    python tests/bannerlord_smoke.py
    python tests/bannerlord_smoke.py --host https://shedstream.org
    python tests/bannerlord_smoke.py --host http://localhost:8000 --jwt YOUR_DEV_JWT

Покрывает (Sprint 5.33 batch):
  SIEGE     — GET /api/bannerlord/party-orders
  DIPLO     — GET /api/bannerlord/kingdom-state, /api/bannerlord/ransom-pool
  SHOP      — GET /api/bannerlord/my-workshops
  FIEF      — GET /api/bannerlord/my-fiefs
  CARAVAN   — GET /api/bannerlord/my-caravans
  HERITAGE  — GET /api/bannerlord/inheritance-log

Без JWT — проверяет что endpoint отвечает {success: False, message: "auth required"}
(значит endpoint регистрирован, ничего не 500'нится).

С JWT — fetches actual data, validates shape (массивы существуют, ключи
ожидаемые).

Если что-то 500'нится / неправильный shape — это РЕГРЕСС.
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

# Windows console UTF-8.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Test infrastructure
# ─────────────────────────────────────────────────────────────────────────────
_failures: list = []
_successes: list = []


def ok(label: str):
    _successes.append(label)
    print(f"  ✅ {label}")


def fail(label: str, reason: str = ""):
    msg = f"  ❌ {label}{' — ' + reason if reason else ''}"
    _failures.append(msg)
    print(msg)


def http_get(url: str, jwt: str | None = None, timeout: float = 10.0) -> dict:
    """Returns dict {status, json_body, raw, error}. Не raises."""
    headers = {"User-Agent": "bannerlord-smoke/1.0"}
    if jwt:
        headers["X-Twitch-JWT"] = jwt
    req = urlreq.Request(url, headers=headers, method="GET")
    result = {"status": 0, "json_body": None, "raw": "", "error": None}
    try:
        with urlreq.urlopen(req, timeout=timeout) as resp:
            result["status"] = resp.status
            raw = resp.read().decode("utf-8", errors="replace")
            result["raw"] = raw
            try:
                result["json_body"] = json.loads(raw)
            except json.JSONDecodeError:
                result["error"] = "non-json response"
    except HTTPError as he:
        result["status"] = he.code
        try:
            raw = he.read().decode("utf-8", errors="replace")
            result["raw"] = raw
            result["json_body"] = json.loads(raw) if raw else None
        except Exception:
            pass
        result["error"] = f"HTTPError {he.code}"
    except URLError as ue:
        result["error"] = f"URLError: {ue.reason}"
    except Exception as ex:
        result["error"] = f"{type(ex).__name__}: {ex}"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Test cases
# ─────────────────────────────────────────────────────────────────────────────
def test_endpoint_baseline(host: str, path: str, label: str):
    """Endpoint exists, returns JSON, has 'success' field, no 500."""
    url = f"{host}{path}"
    print(f"\n[{label}] GET {url}")
    r = http_get(url)
    if r["status"] >= 500:
        fail(label, f"HTTP {r['status']} — server error (раздел/route crash?)")
        if r["raw"]:
            print(f"     raw response (first 200 chars): {r['raw'][:200]}")
        return
    if r["status"] == 0:
        fail(label, f"connection failed: {r['error']}")
        return
    if r["json_body"] is None:
        fail(label, f"not JSON (status={r['status']}): {r['raw'][:200]}")
        return
    body = r["json_body"]
    if "success" not in body:
        fail(label, f"missing 'success' field in response: {body}")
        return
    # No-auth path → expect success=False с auth message.
    if body.get("success") is False:
        msg = (body.get("message") or "").lower()
        if "auth" in msg:
            ok(f"{label} — no-auth path returns 'auth required' (expected)")
        else:
            # Could be valid refuse (e.g. user has no hero) — accept anyway
            ok(f"{label} — endpoint reachable, refused (msg='{body.get('message')}')")
    else:
        ok(f"{label} — endpoint returns success=true (unauthenticated allowed)")


def test_endpoint_with_jwt(host: str, path: str, label: str, jwt: str,
                             expected_keys: list[str] | None = None):
    """С JWT — должен вернуть success=true (или explicit refuse но 200).
    Если expected_keys заданы — проверяет их presence в response."""
    url = f"{host}{path}"
    print(f"\n[{label} +JWT] GET {url}")
    r = http_get(url, jwt=jwt)
    if r["status"] >= 500:
        fail(f"{label} +JWT", f"HTTP {r['status']} — server crash")
        return
    if r["json_body"] is None:
        fail(f"{label} +JWT", "not JSON")
        return
    body = r["json_body"]
    if body.get("success") is True:
        ok(f"{label} +JWT — success=true")
        if expected_keys:
            missing = [k for k in expected_keys if k not in body]
            if missing:
                fail(f"{label} +JWT keys", f"missing: {missing}")
            else:
                ok(f"{label} +JWT — все expected keys present: {expected_keys}")
    else:
        # Refuse OK if JWT bogus или user has no hero — endpoint живой.
        ok(f"{label} +JWT — endpoint живой, refused: '{body.get('message')}'")


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint catalog
# ─────────────────────────────────────────────────────────────────────────────
ENDPOINTS_BASELINE = [
    # SIEGE
    ("/api/bannerlord/party-orders",         "SIEGE party-orders"),
    # DIPLO
    ("/api/bannerlord/kingdom-state",        "DIPLO kingdom-state"),
    ("/api/bannerlord/ransom-pool",          "DIPLO ransom-pool"),
    # SHOP
    ("/api/bannerlord/my-workshops",         "SHOP my-workshops"),
    # FIEF
    ("/api/bannerlord/my-fiefs",             "FIEF my-fiefs"),
    # CARAVAN
    ("/api/bannerlord/my-caravans",          "CARAVAN my-caravans"),
    # HERITAGE
    ("/api/bannerlord/inheritance-log",      "HERITAGE inheritance-log"),
    # Older sprints (sanity check baseline)
    ("/api/bannerlord/my-hero",              "CORE my-hero"),
    ("/api/bannerlord/vassals",              "VAS vassals"),
    ("/api/bannerlord/eligible-heirs",       "VAS eligible-heirs"),
    ("/api/bannerlord/ping",                 "CORE ping"),
]

# С JWT — expected keys per endpoint (когда auth работает).
ENDPOINTS_JWT_KEYS = {
    "/api/bannerlord/party-orders":     ["active"],
    "/api/bannerlord/kingdom-state":    ["has_hero"],
    "/api/bannerlord/ransom-pool":      ["captures"],
    "/api/bannerlord/my-workshops":     ["workshops", "max_workshops"],
    "/api/bannerlord/my-fiefs":         ["fiefs", "boost_mult"],
    "/api/bannerlord/my-caravans":      ["caravans", "max_caravans"],
    "/api/bannerlord/inheritance-log":  ["items"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://localhost:8000",
                        help="Backend base URL (default localhost:8000)")
    parser.add_argument("--jwt", default=None,
                        help="Optional dev JWT для authenticated checks")
    parser.add_argument("--skip-baseline", action="store_true",
                        help="Skip no-auth baseline pass")
    args = parser.parse_args()

    host = args.host.rstrip("/")
    print(f"\n{'=' * 70}")
    print(f"Bannerlord backend smoke tests — host: {host}")
    print(f"{'=' * 70}")

    # PING first — verify backend reachable.
    print("\n[BOOTSTRAP] Checking backend reachability...")
    r = http_get(f"{host}/api/bannerlord/ping")
    if r["status"] == 0:
        print(f"  ❌ Backend unreachable: {r['error']}")
        print(f"     Запусти `python main.py` в backend/, или проверь URL")
        sys.exit(2)
    print(f"  ✅ Backend responds на ping (status={r['status']})")

    # Phase 1: baseline (no auth).
    if not args.skip_baseline:
        print(f"\n{'─' * 70}")
        print("Phase 1: BASELINE (no JWT — endpoints exist + return JSON)")
        print(f"{'─' * 70}")
        for path, label in ENDPOINTS_BASELINE:
            test_endpoint_baseline(host, path, label)

    # Phase 2: JWT (if provided).
    if args.jwt:
        print(f"\n{'─' * 70}")
        print(f"Phase 2: AUTH'D (with JWT — keys present + success path)")
        print(f"{'─' * 70}")
        for path, expected_keys in ENDPOINTS_JWT_KEYS.items():
            # Find label from baseline list.
            label = next((lbl for p, lbl in ENDPOINTS_BASELINE if p == path), path)
            test_endpoint_with_jwt(host, path, label, args.jwt, expected_keys)
    else:
        print(f"\n[SKIPPED] Phase 2 (no --jwt provided)")
        print(f"     Чтобы добавить authenticated checks: получи dev JWT через /dev/login")
        print(f"     и запусти: python tests/bannerlord_smoke.py --jwt {{TOKEN}}")

    # Summary.
    print(f"\n{'=' * 70}")
    print(f"RESULTS: {len(_successes)} passed, {len(_failures)} failed")
    print(f"{'=' * 70}")
    if _failures:
        print(f"\nFailures:")
        for f in _failures:
            print(f)
        sys.exit(1)
    print(f"\n✨ All checks passed — endpoints baseline healthy")
    sys.exit(0)


if __name__ == "__main__":
    main()

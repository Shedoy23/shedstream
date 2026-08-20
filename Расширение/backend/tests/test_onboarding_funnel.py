# -*- coding: utf-8 -*-
"""Приём событий воронки онбординга (ROADMAP §R4).

ЗАЧЕМ ИМЕННО ЭТИ ПРОВЕРКИ. Воронка — это прибор, по которому будут принимать
решения о продукте. Прибор, которому можно приписать чужой успех или который
схлопывает вторую попытку в первую, хуже отсутствующего: он не молчит, он врёт.

Держим четыре свойства:
  1. ранние шаги принимаются БЕЗ токена — иначе не увидим тех, кто отвалился
     до входа в Twitch, а это самая интересная часть воронки;
  2. `channel_id` берётся ИЗ ТОКЕНА и никогда из тела;
  3. выводимые события (первое действие зрителя и т.п.) снаружи не принимаются;
  4. повтор из-за сети схлопывается, а вторая честная попытка — нет.

Запуск: python tests/test_onboarding_funnel.py   (судить по коду возврата)
"""
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
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_onboarding_")
os.close(_fd)
os.unlink(db_path)
os.environ["DB_PATH"] = db_path

CHANNEL_ID = 98319857
OTHER_CHANNEL = 55555555

passed = 0
failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print("  OK   " + message)
    else:
        failed += 1
        print("  FAIL " + message)


def request(method, path, body=b"", query="", content_type="", authorization=""):
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
    if authorization:
        headers.append((b"authorization", authorization.encode("ascii")))
    return Request({
        "type": "http", "http_version": "1.1", "method": method, "scheme": "https",
        "path": path, "raw_path": path.encode("ascii"),
        "query_string": query.encode("ascii"), "headers": headers,
        "client": ("127.0.0.1", 12345), "server": ("testserver", 443),
    }, receive)


def json_request(path, payload_dict, authorization=""):
    return request("POST", path, json.dumps(payload_dict).encode("utf-8"),
                   content_type="application/json", authorization=authorization)


def form_request(path, payload_dict):
    return request("POST", path, urlencode(payload_dict).encode("utf-8"),
                   content_type="application/x-www-form-urlencoded")


def payload(response):
    return json.loads(response.body.decode("utf-8"))


async def rows(db, **where):
    clause = " AND ".join("%s=?" % k for k in where) or "1=1"
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT event, installation_id, channel_id, result, client_event_id "
            "FROM onboarding_events WHERE " + clause + " ORDER BY id",
            tuple(where.values()))
        return await cur.fetchall()


async def main() -> int:
    import dependencies
    import manager_auth
    import main as main_mod
    from database import Database
    from modules._loader import discover_modules
    from routes import manager as routes

    db = Database(db_path)
    original_cookie = routes._read_session_cookie
    original_rate = routes.check_rate_limit
    try:
        await db.init_tables()
        await main_mod.run_migrations()
        async with db._connect() as conn:
            cols = await (await conn.execute("PRAGMA table_info(channels)")).fetchall()
            if "approved" not in {c[1] for c in cols}:
                await conn.execute(
                    "ALTER TABLE channels ADD COLUMN approved INTEGER NOT NULL DEFAULT 0")
            await conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id,login,display_name,tier,approved) "
                "VALUES (?, 'alice', 'Alice', 'free', 1)", (CHANNEL_ID,))
            await conn.commit()
        dependencies.set_db(db)
        discover_modules()
        routes._read_session_cookie = lambda _r: CHANNEL_ID
        routes.check_rate_limit = lambda *a, **k: True

        INSTALL = "install-abc-0001"

        # ── 1. Ранние шаги — без токена ──────────────────────────────────────
        r = await routes.manager_onboarding_events(json_request(
            "/v1/manager/onboarding",
            {"events": [
                {"event": "manager_started", "installation_id": INSTALL,
                 "manager_version": "0.1.0-alpha.10", "client_event_id": "e1"},
                {"event": "game_detection_started", "installation_id": INSTALL,
                 "client_event_id": "e2"},
            ]}))
        body = payload(r)
        check(r.status_code == 200 and body["accepted"] == 2,
              "шаги до входа в Twitch принимаются без токена (принято: %s)"
              % body.get("accepted"))
        pre = await rows(db, installation_id=INSTALL)
        check(len(pre) == 2 and all(row[2] is None for row in pre),
              "у событий до входа нет канала — установка пока анонимна")

        # ── 2. Шаг после входа без токена — отказ ────────────────────────────
        r = await routes.manager_onboarding_events(json_request(
            "/v1/manager/onboarding",
            {"events": [{"event": "technical_ready", "installation_id": INSTALL,
                         "client_event_id": "e3"}]}))
        body = payload(r)
        check(body["accepted"] == 0 and "auth_required" in body["rejected"],
              "«готовность» без токена не принимается — иначе успех можно "
              "приписать себе кнопкой")

        # ── 3. С токеном: канал берётся ИЗ ТОКЕНА, а не из тела ──────────────
        secret = "manager-onboarding-device-secret-32-plus-chars"
        create = await routes.manager_pairing_create(json_request(
            "/v1/manager/pairings",
            {"installation_id": INSTALL, "module_id": "bannerlord",
             "device_challenge": manager_auth.device_challenge(secret)}))
        assert create.status_code == 200, create.body
        created = payload(create)
        page = await routes.manager_pair_page(request(
            "GET", "/manager/pair", query="code=" + created["user_code"]))
        csrf = re.search(r"name='csrf' value='([^']+)'",
                         page.body.decode("utf-8")).group(1)
        await routes.manager_pair_decide(form_request(
            "/manager/pair",
            {"pairing_id": created["pairing_id"], "csrf": csrf, "decision": "approve"}))
        exchanged = await routes.manager_pairing_exchange(
            created["pairing_id"], json_request("/exchange", {"device_secret": secret}))
        bearer = "Bearer " + payload(exchanged)["access_token"]

        r = await routes.manager_onboarding_events(json_request(
            "/v1/manager/onboarding",
            {"events": [{"event": "technical_ready", "installation_id": INSTALL,
                         "channel_id": OTHER_CHANNEL,        # попытка подмены
                         "integration_id": "bannerlord",
                         "elapsed_ms": 419000, "result": "ok",
                         "client_event_id": "e4"}]}, bearer))
        check(payload(r)["accepted"] == 1, "с токеном шаг принимается")
        ready = await rows(db, event="technical_ready")
        check(len(ready) == 1 and ready[0][2] == CHANNEL_ID,
              "канал взят из токена, подставленный в теле чужой канал "
              "проигнорирован (записано: %s)" % (ready[0][2] if ready else None))
        check(not await rows(db, channel_id=OTHER_CHANNEL),
              "чужому каналу не приписалось ничего")

        # ── 4. Выводимые события снаружи не принимаются ──────────────────────
        r = await routes.manager_onboarding_events(json_request(
            "/v1/manager/onboarding",
            {"events": [{"event": "first_viewer_action", "installation_id": INSTALL,
                         "client_event_id": "e5"}]}, bearer))
        body = payload(r)
        check(body["accepted"] == 0 and "derived_event_not_accepted" in body["rejected"],
              "«первое действие зрителя» нельзя прислать — его выводит бэкенд")

        # ── 5. Незнакомое имя события ────────────────────────────────────────
        r = await routes.manager_onboarding_events(json_request(
            "/v1/manager/onboarding",
            {"events": [{"event": "everything_is_great", "installation_id": INSTALL,
                         "client_event_id": "e6"}]}, bearer))
        check("unknown_event" in payload(r)["rejected"],
              "имя не из словаря отвергается, таблица не превращается в свалку")

        # ── 6. Повтор из-за сети схлопывается ────────────────────────────────
        dup = {"events": [{"event": "install_started", "installation_id": INSTALL,
                           "integration_id": "bannerlord", "client_event_id": "e7"}]}
        first = payload(await routes.manager_onboarding_events(
            json_request("/v1/manager/onboarding", dup, bearer)))
        second = payload(await routes.manager_onboarding_events(
            json_request("/v1/manager/onboarding", dup, bearer)))
        check(first["accepted"] == 1 and second["accepted"] == 0
              and second["ignored_duplicates"] == 1,
              "ретрай той же посылки не удваивает шаг воронки")

        # ── 7. …а вторая ЧЕСТНАЯ попытка остаётся отдельной ──────────────────
        retry = payload(await routes.manager_onboarding_events(json_request(
            "/v1/manager/onboarding",
            {"events": [{"event": "install_started", "installation_id": INSTALL,
                         "integration_id": "bannerlord", "result": "retry_after_fail",
                         "client_event_id": "e8"}]}, bearer)))
        starts = await rows(db, event="install_started")
        check(retry["accepted"] == 1 and len(starts) == 2,
              "повторная установка после неудачи видна отдельным событием — "
              "иначе воронка спрячет ровно то, ради чего её завели (записей: %d)"
              % len(starts))

        # ── 8. Длинные поля обрезаются, путь целиком не сохраняется ──────────
        long_path = "C:\\Users\\Someone\\AppData\\Roaming\\" + "x" * 400
        await routes.manager_onboarding_events(json_request(
            "/v1/manager/onboarding",
            {"events": [{"event": "install_completed", "installation_id": INSTALL,
                         "result": long_path, "client_event_id": "e9"}]}, bearer))
        done = await rows(db, event="install_completed")
        check(done and len(done[0][3]) <= 120,
              "длинные значения обрезаются (получено %d символов)"
              % (len(done[0][3]) if done else -1))

        print("=" * 70)
        print("PASSED: %d   FAILED: %d" % (passed, failed))
        print("ALL GREEN — воронка принимает только то, что должна."
              if not failed else "КРАСНО — прибор врёт.")
        return 1 if failed else 0
    finally:
        routes._read_session_cookie = original_cookie
        routes.check_rate_limit = original_rate
        try:
            os.unlink(db_path)
        except OSError:
            pass


def _run() -> int:
    try:
        return asyncio.run(main())
    except Exception:
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    code = _run()
    sys.stdout.flush()
    os._exit(code)

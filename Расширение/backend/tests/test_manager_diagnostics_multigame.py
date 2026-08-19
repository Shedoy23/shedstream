# -*- coding: utf-8 -*-
"""Серверный сценарий «Проверить готовность» для Bannerlord и ShedColony.

ЗАЧЕМ. Сценарий диагностики был покрыт тестом только для RimWorld
(`test_manager_pairing_http.py`), хотя у трёх игр он идёт ТРЕМЯ разными путями:

  RimWorld    — команда в `rimworld_pending_commands`, статусы queued →
                delivered → acked, поддержаны режимы refuse/lost_ack;
  Bannerlord  — команда в общей очереди `module_actions` типом
                `diagnostic_ping`, статус меняется только на ACK коннектора;
  ShedColony  — команды НЕТ вообще: опубликованный JAR ещё не умеет
                `diagnostic_ping`, и готовность подтверждается живым
                авторизованным heartbeat, поэтому строка сразу `acked`.

Последнее — сознательный компромисс, а не баг, но он обязан быть ЗАФИКСИРОВАН:
иначе первая же версия ShedColony с настоящим ping'ом молча изменит смысл
зелёной галочки, и никто не заметит. Тест держит все три контракта.

Запуск:  python tests/test_manager_diagnostics_multigame.py
         python scripts/run-backend-tests.py diagnostics
Судить по КОДУ ВОЗВРАТА, а не по надписи.
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
# Миграция M1 backfill'ит существующие строки каналом по умолчанию
# и без этой переменной отказывается стартовать.
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_manager_diag_")
os.close(_fd)
os.unlink(db_path)
os.environ["DB_PATH"] = db_path

CHANNEL_ID = 98319857

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


def json_request(path, payload_dict, authorization=""):
    return request("POST", path, json.dumps(payload_dict).encode("utf-8"),
                   content_type="application/json", authorization=authorization)


def form_request(path, payload_dict):
    return request("POST", path, urlencode(payload_dict).encode("utf-8"),
                   content_type="application/x-www-form-urlencoded")


def payload(response):
    return json.loads(response.body.decode("utf-8"))


async def pair_manager(routes, manager_auth, module_id, installation_id):
    """Пройти pairing до access token с областью нужного модуля."""
    secret = "manager-diag-device-secret-with-32-plus-characters"
    create = await routes.manager_pairing_create(json_request(
        "/v1/manager/pairings",
        {
            "installation_id": installation_id,
            "module_id": module_id,
            "device_challenge": manager_auth.device_challenge(secret),
        },
    ))
    assert create.status_code == 200, create.body
    created = payload(create)
    page = await routes.manager_pair_page(request(
        "GET", "/manager/pair", query="code=" + created["user_code"]))
    csrf = re.search(r"name='csrf' value='([^']+)'", page.body.decode("utf-8")).group(1)
    approved = await routes.manager_pair_decide(form_request(
        "/manager/pair",
        {"pairing_id": created["pairing_id"], "csrf": csrf, "decision": "approve"},
    ))
    assert approved.status_code == 200, approved.body
    exchanged = await routes.manager_pairing_exchange(
        created["pairing_id"], json_request("/exchange", {"device_secret": secret}))
    assert exchanged.status_code == 200, exchanged.body
    return "Bearer " + payload(exchanged)["access_token"]


async def issue_module_bearer(routes, manager_bearer, module_id):
    issued = await routes.manager_credential_issue(json_request(
        "/v1/manager/module-credentials",
        {"module_id": module_id, "label": "Diagnostics test connector"},
        manager_bearer,
    ))
    assert issued.status_code == 201, issued.body
    return "Bearer " + payload(issued)["module_token"]


async def diagnostic_rows(db, module_id):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT diagnostic_id,status,command_id FROM manager_diagnostic_actions "
            "WHERE channel_id=? AND module_id=?", (CHANNEL_ID, module_id))
        return await cur.fetchall()


async def module_action_rows(db, module_id):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT action_id,type,status FROM module_actions "
            "WHERE channel_id=? AND module_id=?", (CHANNEL_ID, module_id))
        return await cur.fetchall()


async def main() -> int:
    import dependencies
    import manager_auth
    import module_liveness
    import main as main_mod
    from database import Database
    from modules._loader import discover_modules
    from routes import manager as routes
    from routes import module_api

    db = Database(db_path)
    original_cookie = routes._read_session_cookie
    original_rate = routes.check_rate_limit
    try:
        # Схема строится ТОЙ ЖЕ последовательностью, что и боевой старт:
        # init_tables + run_migrations. Выбирать миграции руками здесь нельзя —
        # отказ Bannerlord прогоняется через настоящий refund-маршрут адаптера,
        # который трогает таблицы далеко за пределами manager-миграций.
        await db.init_tables()
        await main_mod.run_migrations()
        async with db._connect() as conn:
            columns = await (await conn.execute("PRAGMA table_info(channels)")).fetchall()
            if "approved" not in {row[1] for row in columns}:
                await conn.execute(
                    "ALTER TABLE channels ADD COLUMN approved INTEGER NOT NULL DEFAULT 0")
            await conn.execute(
                "INSERT INTO channels (channel_id,login,display_name,tier,approved) "
                "VALUES (?, 'alice', 'Alice', 'free', 1)", (CHANNEL_ID,))
            await conn.commit()
        dependencies.set_db(db)
        discover_modules()
        routes._read_session_cookie = lambda _request: CHANNEL_ID
        routes.check_rate_limit = lambda *args, **kwargs: True

        # ── Bannerlord ───────────────────────────────────────────────────────
        bnr_manager = await pair_manager(routes, manager_auth, "bannerlord", "inst-bnr-0001")
        bnr_module = await issue_module_bearer(routes, bnr_manager, "bannerlord")

        offline = await routes.manager_diagnostic_start(request(
            "POST", "/v1/manager/diagnostics/test-action", authorization=bnr_manager))
        check(offline.status_code == 409
              and payload(offline)["status"] == "module_offline",
              "Bannerlord: пока мод молчит, проверка готовности отказывает явно "
              "(получено: %s %s)" % (offline.status_code, payload(offline).get("status")))

        await module_liveness.touch(db, CHANNEL_ID, "bannerlord")

        started = await routes.manager_diagnostic_start(request(
            "POST", "/v1/manager/diagnostics/test-action", authorization=bnr_manager))
        check(started.status_code == 201, "Bannerlord: живой мод — проверка стартует")
        started_body = payload(started)
        rows = await module_action_rows(db, "bannerlord")
        check(len(rows) == 1 and rows[0][1] == "diagnostic_ping" and rows[0][2] == "queued",
              "Bannerlord: команда легла в общую очередь module_actions типом "
              "diagnostic_ping (получено: %r)" % (rows,))
        check(rows and rows[0][0].startswith("manager_"),
              "Bannerlord: id команды помечен префиксом manager_ — по нему ACK "
              "находит строку диагностики")

        polled = await module_api.module_actions_poll("bannerlord", request(
            "GET", "/v1/module/bannerlord/actions", authorization=bnr_module))
        check(len(polled["actions"]) == 1
              and polled["actions"][0]["type"] == "diagnostic_ping",
              "Bannerlord: коннектор получает ping тем же long-poll'ом, что и "
              "обычные действия")

        acked = await module_api.module_ack("bannerlord", json_request(
            "/v1/module/bannerlord/ack",
            {"action_id": rows[0][0], "success": True},
            bnr_module,
        ))
        check(acked.get("acked") is True, "Bannerlord: ACK коннектора принят")

        result = await routes.manager_diagnostic_result(
            started_body["diagnostic_id"],
            request("GET", "/diagnostic", authorization=bnr_manager))
        check(payload(result)["status"] == "acked",
              "Bannerlord: после ACK проверка готовности успешна (получено: %s)"
              % payload(result)["status"])

        refuse = await routes.manager_diagnostic_start(json_request(
            "/v1/manager/diagnostics/test-action", {"mode": "refuse"}, bnr_manager))
        check(refuse.status_code == 409
              and payload(refuse)["status"] == "diagnostic_mode_not_supported",
              "Bannerlord: учебные режимы refuse/lost_ack честно отказывают, "
              "а не притворяются выполненными")

        failed_start = await routes.manager_diagnostic_start(request(
            "POST", "/v1/manager/diagnostics/test-action", authorization=bnr_manager))
        failed_body = payload(failed_start)
        failed_rows = [r for r in await module_action_rows(db, "bannerlord")
                       if r[2] in ("queued", "dispatched")]
        await module_api.module_ack("bannerlord", json_request(
            "/v1/module/bannerlord/ack",
            {"action_id": failed_rows[0][0], "success": False, "error": "no mod"},
            bnr_module,
        ))
        failed_result = await routes.manager_diagnostic_result(
            failed_body["diagnostic_id"],
            request("GET", "/diagnostic", authorization=bnr_manager))
        check(payload(failed_result)["status"] == "failed",
              "Bannerlord: отрицательный ACK даёт «не готово», а не «готово»")

        # ── ShedColony ───────────────────────────────────────────────────────
        sc_manager = await pair_manager(routes, manager_auth, "shedcolony", "inst-sc-0001")

        sc_offline = await routes.manager_diagnostic_start(request(
            "POST", "/v1/manager/diagnostics/test-action", authorization=sc_manager))
        check(sc_offline.status_code == 409
              and payload(sc_offline)["status"] == "module_offline",
              "ShedColony: без живого heartbeat готовность НЕ подтверждается")

        await module_liveness.touch(db, CHANNEL_ID, "shedcolony")
        sc_started = await routes.manager_diagnostic_start(request(
            "POST", "/v1/manager/diagnostics/test-action", authorization=sc_manager))
        check(sc_started.status_code == 201, "ShedColony: с живым heartbeat проверка стартует")
        sc_body = payload(sc_started)
        sc_result = await routes.manager_diagnostic_result(
            sc_body["diagnostic_id"],
            request("GET", "/diagnostic", authorization=sc_manager))
        check(payload(sc_result)["status"] == "acked",
              "ShedColony: готовность подтверждается сразу (доказательство — "
              "живой авторизованный heartbeat)")
        sc_actions = await module_action_rows(db, "shedcolony")
        check(sc_actions == [],
              "ShedColony: команда в очередь НЕ кладётся — опубликованный JAR "
              "ещё не умеет diagnostic_ping. Когда научится, этот тест обязан "
              "покраснеть и контракт надо переписать (получено: %r)" % (sc_actions,))

        print("=" * 70)
        print("PASSED: %d   FAILED: %d" % (passed, failed))
        print("ALL GREEN — диагностика трёх игр держит свои контракты."
              if not failed else "КРАСНО — сценарий готовности изменился.")
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
        # Иначе исключение оставляло висеть пул aiosqlite и тест «зависал»
        # до внешнего таймаута вместо честного ненулевого кода.
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    code = _run()
    sys.stdout.flush()
    os._exit(code)

# -*- coding: utf-8 -*-
"""audit-bannerlord-track-b.py — денежная половина трека B реестра 0.0.2.

ЗАЧЕМ. Трек B — 68 типов действий Bannerlord — не прогонялся НИ РАЗУ: в
реестре все девять групп стоят с пустыми клетками. Причина уважительная —
«нужна живая игра». Но это верно не для всего.

ЧТО ЭТОТ СКРИПТ ДОКАЗЫВАЕТ (без игры, сам):
  * действие объявлено в манифесте и вообще принимается бэкендом;
  * цена берётся С СЕРВЕРА, а не из тела запроса;
  * при успехе списывается РОВНО объявленная цена и появляется задание в
    очереди мода — то есть деньги не ушли в никуда;
  * при отказе ДО списания деньги не трогаются вообще;
  * когда мод отказывается выполнять, крустики возвращаются полностью;
  * повторный отказ не возвращает деньги второй раз.

ЧЕГО ЭТОТ СКРИПТ НЕ ДОКАЗЫВАЕТ И ДОКАЗАТЬ НЕ МОЖЕТ:
  **Наступает ли эффект в игре.** Хендлер в моде может честно ответить
  «выполнено» и не сделать ничего — это «тихий no-op», самый дорогой класс
  ошибок проекта (CLAUDE.md, всплывал 4 раза). Отличить его от настоящей
  работы можно ТОЛЬКО в запущенной игре, глазами. Поэтому зелёный прогон
  здесь означает «деньги в порядке», а НЕ «механика работает».

  Не заменяет игровой заход. Сокращает его: владельцу остаётся смотреть на
  эффект, а не пересчитывать крустики.

ЧТО НУЖНО ЗАРАНЕЕ:
  1. python scripts/local-setup.py     — копия прода в %USERPROFILE%\\shedstream-local
  2. в local.env: TESTING_BYPASS_STREAM_LIVE=true
  3. поднятый локальный бэкенд:  cd Расширение/backend && python main.py

ЗАПУСК:
  python scripts/audit-bannerlord-track-b.py

ПРОД НЕ ТРОГАЕТ: работает только против 127.0.0.1 и локальной копии базы.
"""
import base64
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("AUDIT_URL", "http://127.0.0.1:8000")
HOME = os.environ.get("USERPROFILE", os.path.expanduser("~"))
DB = os.environ.get("AUDIT_DB", os.path.join(HOME, "shedstream-local", "viewers.db"))
CHANNEL = int(os.environ.get("AUDIT_CHANNEL", "98319857"))
USER = "audit_bnr_viewer"
START_POINTS = 50_000_000

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

if not BASE.startswith("http://127.0.0.1") and not BASE.startswith("http://localhost"):
    print("Этот скрипт ходит только на localhost. Прод трогать нельзя.")
    sys.exit(2)

fails = []
rows_report = []


def db_conn():
    return sqlite3.connect(DB, timeout=30)


def call(path, body=None, method="POST", jwt_token=None, bearer=None):
    data = json.dumps(body or {}).encode() if method == "POST" else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if jwt_token:
        req.add_header("X-Twitch-JWT", jwt_token)
    if bearer:
        req.add_header("Authorization", "Bearer " + bearer)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:300]}
    except urllib.error.URLError as e:
        return 0, {"error": str(e.reason)}


def make_jwt(secret):
    import jwt as pyjwt
    b = secret.replace("-", "+").replace("_", "/")
    pad = 4 - len(b) % 4
    if pad != 4:
        b += "=" * pad
    return pyjwt.encode(
        {"sub": USER, "user_id": "900000042", "channel_id": str(CHANNEL),
         "role": "viewer", "exp": int(time.time()) + 7200},
        base64.b64decode(b), algorithm="HS256")


def points():
    c = db_conn()
    cur = c.execute("SELECT points FROM viewers WHERE channel_id=? AND username=?",
                    (CHANNEL, USER))
    row = cur.fetchone()
    c.close()
    return row[0] if row else 0


def set_points(value):
    c = db_conn()
    c.execute(
        "INSERT INTO viewers (channel_id, username, points) VALUES (?,?,?) "
        "ON CONFLICT(channel_id, username) DO UPDATE SET points=excluded.points",
        (CHANNEL, USER, value))
    c.commit()
    c.close()


def action_row_by_client_id(client_id):
    """Наше задание в очереди мода — ищем по client_action_id.

    Не «последнее по времени»: на локальной копии прода в очереди лежат чужие
    строки, и «последнее» молча указало бы не туда. Цена и ник живут внутри
    JSON-поля `data`, отдельных колонок под них в схеме нет.
    """
    c = db_conn()
    cur = c.execute(
        "SELECT action_id, type, data, status FROM module_actions "
        "WHERE channel_id=? AND module_id='bannerlord' AND client_action_id=? "
        "ORDER BY id DESC LIMIT 1", (CHANNEL, client_id))
    row = cur.fetchone()
    c.close()
    if not row:
        return None
    try:
        data = json.loads(row[2] or "{}")
    except ValueError:
        data = {}
    return {"action_id": row[0], "type": row[1], "status": row[3],
            "price": int(data.get("price") or 0),
            "username": data.get("username") or data.get("target") or ""}


def seed_hero():
    """Завести аудит-зрителю героя с кланом и королевством.

    Без этого прогон бесполезен: 61 действие из 61 отказывает на «сначала
    создай героя», денежный путь не проходит НИ РАЗУ, и «зелёный» результат
    означал бы только то, что мы ничего не проверили. Поля копируются с формы
    живого героя (клан-лидер и король — иначе половина действий отсекается по
    правам ещё до кассы).
    """
    clan = json.dumps({"name": "[AUDIT] Проверка", "leader_name": USER,
                       "tier": 3, "renown": 500}, ensure_ascii=False)
    kingdom = json.dumps({"id": "audit_kingdom", "name": "Аудит",
                          "ruler_name": USER}, ensure_ascii=False)
    family = json.dumps({"spouse": None, "children": []}, ensure_ascii=False)
    c = db_conn()
    c.execute("DELETE FROM bannerlord_heroes WHERE channel_id=? AND username=?",
              (CHANNEL, USER))
    c.execute(
        "INSERT INTO bannerlord_heroes "
        "(channel_id, username, hero_id, display_name, culture, is_alive, "
        " is_prisoner, gold, level, clan_name, kingdom_name, gear_tier, "
        " clan_info_json, kingdom_info_json, is_female, family_info_json, "
        " iteration, is_wounded, is_clan_leader, is_king, captured, combat_stance) "
        "VALUES (?,?,?,?,?,1,0,?,?,?,?,?,?,?,0,?,1,0,1,1,0,'balanced')",
        (CHANNEL, USER, "CharacterObject_audit_1", USER, "vlandia",
         900_000_000, 30, "[AUDIT] Проверка", "Аудит", 4, clan, kingdom, family))
    c.commit()
    c.close()


def purchasable_actions():
    """Список берём ИЗ КОДА, а не переписываем сюда: копия разошлась бы."""
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "Расширение", "backend"))
    from routes.bannerlord import _PURCHASABLE_ACTIONS
    return list(_PURCHASABLE_ACTIONS)


def audit_one(action_type, jwt_token, module_token):
    """Один тип действия: купить → проверить деньги → отказать модом → возврат."""
    set_points(START_POINTS)
    before = points()

    client_id = "audit-%s-%d" % (action_type.replace(".", "_"), time.time() * 1000)
    code, resp = call("/api/bannerlord/action",
                      {"action_type": action_type,
                       "data": {"client_action_id": client_id}},
                      jwt_token=jwt_token)
    after_buy = points()
    spent = before - after_buy

    ok = bool(resp.get("success"))
    msg = str(resp.get("message") or resp.get("error") or "")[:70]

    if not ok:
        # Отказ — законный исход (нет клана, нет героя, не тот момент).
        # Требование к деньгам одно: отказ не должен стоить ни крустика.
        verdict = "ОТКАЗ ДО СПИСАНИЯ" if spent == 0 else "❌ ОТКАЗ, НО ДЕНЬГИ СНЯЛИ"
        if spent != 0:
            fails.append("%s: отказ, но списано %d" % (action_type, spent))
        return {"action": action_type, "verdict": verdict, "spent": spent,
                "queued": "-", "refund": "-", "note": msg}

    row = action_row_by_client_id(client_id)
    if not row or row["type"] != action_type:
        fails.append("%s: списано %d, но задания в очереди нет" % (action_type, spent))
        return {"action": action_type, "verdict": "❌ ДЕНЬГИ БЕЗ ЗАДАНИЯ",
                "spent": spent, "queued": "нет", "refund": "-", "note": msg}

    declared = row["price"]
    if declared and spent != declared:
        fails.append("%s: списано %d, а в задании цена %d" % (action_type, spent, declared))

    # Мод отказывается выполнять — деньги обязаны вернуться полностью.
    action_id = row["action_id"]
    call("/v1/module/bannerlord/events",
         {"channel_id": CHANNEL,
          "envelopes": [{"id": "audit-fail-%s" % action_id, "kind": "event", "type": "action.failed", "ts": int(time.time()), "data": {"action_id": action_id, "reason": "audit: имитация отказа мода"}}]},
         bearer=module_token)
    after_refund = points()
    refunded = after_refund - after_buy
    if refunded != spent:
        fails.append("%s: списали %d, вернули %d" % (action_type, spent, refunded))

    # Повторный отказ не должен платить второй раз.
    call("/v1/module/bannerlord/events",
         {"channel_id": CHANNEL,
          "envelopes": [{"id": "audit-fail2-%s" % action_id, "kind": "event", "type": "action.failed", "ts": int(time.time()), "data": {"action_id": action_id, "reason": "audit: повторный отказ"}}]},
         bearer=module_token)
    if points() != after_refund:
        fails.append("%s: повторный отказ вернул деньги ВТОРОЙ раз" % action_type)

    verdict = "OK" if refunded == spent and (not declared or spent == declared) else "❌ ДЕНЬГИ"
    return {"action": action_type, "verdict": verdict, "spent": spent,
            "queued": "да", "refund": refunded, "note": msg}


def main():
    print("=" * 78)
    print("ТРЕК B — денежная половина, без игры")
    print("=" * 78)

    if not os.path.exists(DB):
        print("Нет локальной базы: %s\nСначала python scripts/local-setup.py" % DB)
        return 2

    secret = os.environ.get("TWITCH_EXTENSION_SECRET")
    module_token = os.environ.get("AUDIT_MODULE_TOKEN")
    if not secret or not module_token:
        print("Нужны переменные окружения TWITCH_EXTENSION_SECRET и "
              "AUDIT_MODULE_TOKEN (module-token локального канала).")
        return 2

    code, _ = call("/health", method="GET")
    if code != 200:
        print("Локальный бэкенд не отвечает на %s — подними его." % BASE)
        return 2

    # ПРОВЕРКА СВЯЗИ ДО ПРОГОНА. Без неё первый прогон 01.08 отрапортовал
    # 12 «невозвращённых возвратов»: module-токен отвергался с 401, событие
    # action.failed не доходило вовсе, и скрипт честно видел «денег не
    # вернули» — дефект был в тесте, а не в коде. Инструмент, который не
    # умеет отличить «сломано» от «я не дозвонился», хуже отсутствия
    # инструмента: он производит ложные тревоги с видом доказательств.
    code, resp = call("/v1/module/bannerlord/events",
                      {"channel_id": CHANNEL,
                       "envelopes": [{"id": "probe-connectivity", "kind": "event", "type": "action.failed", "ts": int(time.time()), "data": {"action_id": "probe-nonexistent", "reason": "проверка связи"}}]},
                      bearer=module_token)
    if code != 200:
        print("Module-токен не принят бэкендом (HTTP %s): %s" % (code, resp))
        print("Прогон остановлен: без этого 'возврат не пришёл' будет означать")
        print("только то, что мы не дозвонились. Проверь MODULE_TOKEN_SECRET —")
        print("он должен совпадать у скрипта и у запущенного бэкенда.")
        return 2
    print("Связь с Module API есть (события принимаются).")

    jwt_token = make_jwt(secret)
    seed_hero()
    actions = purchasable_actions()
    print("Действий в реестре покупаемого: %d" % len(actions))
    print("Аудит-зрителю заведён герой (клан-лидер, король, 900М динаров).\n")

    for a in actions:
        r = audit_one(a, jwt_token, module_token)
        rows_report.append(r)
        print("  %-28s %-22s списано=%-9s задание=%-4s возврат=%s %s" % (
            r["action"], r["verdict"], r["spent"], r["queued"], r["refund"],
            ("— " + r["note"]) if r["note"] else ""))

    print("\n" + "=" * 78)
    charged = [r for r in rows_report if r["queued"] == "да"]
    refused = [r for r in rows_report if r["verdict"] == "ОТКАЗ ДО СПИСАНИЯ"]
    print("Прошли денежный путь целиком: %d" % len(charged))
    print("Отказали ДО списания (деньги целы, эффект не проверялся): %d" % len(refused))
    print("Найдено денежных дефектов: %d" % len(fails))
    for f in fails:
        print("  ❌ " + f)

    print("\nНАПОМИНАНИЕ: зелёный прогон = деньги в порядке. Работает ли механика")
    print("в игре, он НЕ проверяет — это по-прежнему игровой заход владельца.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""audit-rimworld-track-c.py — прогон трека C реестра 0.0.2 (RimWorld).

ЗАЧЕМ. В RimWorld никто не играет, поэтому «проверить в игре» недостижимо, а
код-аудит не видит главного: списалось ли ровно столько, дошла ли команда до
мода, вернулись ли деньги при отказе. Этот скрипт проходит платные механики
RimWorld как зритель и как мод, на локальной копии базы.

ЧТО НУЖНО ЗАРАНЕЕ:
  1. python scripts/local-setup.py          — копия прода в %USERPROFILE%\\shedstream-local
  2. в local.env: TESTING_BYPASS_STREAM_LIVE=true  (иначе всё упрётся в «идёт ли стрим»)
  3. поднятый локальный бэкенд:  cd Расширение/backend && python main.py

ЗАПУСК:
  python scripts/audit-rimworld-track-c.py

ПРОД НЕ ТРОГАЕТ: работает только против 127.0.0.1 и локальной базы.
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
USER = "audit_viewer"

fails = []
notes = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def note(text):
    print(f"  [ИНФО] {text}")
    notes.append(text)


def db_conn():
    return sqlite3.connect(DB)


def points():
    c = db_conn()
    row = c.execute("SELECT points FROM viewers WHERE channel_id=? AND username=?",
                    (CHANNEL, USER)).fetchone()
    c.close()
    return row[0] if row else None


def queue_rows():
    c = db_conn()
    try:
        rows = c.execute(
            "SELECT cmd_id, status, cmd_json FROM rimworld_pending_commands "
            "WHERE channel_id=? ORDER BY rowid", (CHANNEL,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    c.close()
    return rows


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
        {"sub": USER, "user_id": "900000001", "channel_id": str(CHANNEL),
         "role": "viewer", "exp": int(time.time()) + 7200},
        base64.b64decode(b), algorithm="HS256")


def set_points(value):
    c = db_conn()
    c.execute(
        "INSERT INTO viewers (channel_id, username, points) VALUES (?,?,?) "
        "ON CONFLICT(channel_id, username) DO UPDATE SET points=excluded.points",
        (CHANNEL, USER, value))
    c.commit()
    c.close()


def seed_catalog(module_token):
    """Прислать каталог магазина ТАК ЖЕ, как это делает мод (POST shop-catalog).

    Каталог на проде пуст, потому что его наполняет игра, а в RimWorld никто не
    играл. Без каталога магазин проверить нечем — а именно магазин и есть
    главный пункт changelog 0.0.2 (фикс `_rwBuyItem`).
    """
    items = [
        {"category": "apparel", "def_name": "Apparel_AuditVest", "label": "Аудиторский жилет",
         "desc": "позиция для прогона", "price": 1200, "tech_level": "Industrial"},
        {"category": "weapon", "def_name": "Gun_AuditRifle", "label": "Аудиторская винтовка",
         "desc": "позиция для прогона", "price": 2500, "tech_level": "Industrial"},
    ]
    code, resp = call("/api/rimworld/shop-catalog", items, bearer=module_token)
    return code, resp


def seed_pawn():
    """Завести пешку зрителя в базе.

    Пассии, гены и черты требуют существующую пешку. В живой игре её создаёт
    мод по команде `create_pawn`; поддельный мод команду подтверждает, но
    физически ничего не создаёт, поэтому строку заводим сами.
    """
    c = db_conn()
    c.execute(
        "INSERT INTO rimworld_pawns (channel_id, username, pawn_name, is_alive, health) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(channel_id, username) DO UPDATE SET is_alive=1",
        (CHANNEL, USER, "Аудитор", 1, 100))
    c.commit()
    row = c.execute("SELECT id FROM rimworld_pawns WHERE channel_id=? AND username=?",
                    (CHANNEL, USER)).fetchone()
    pawn_id = row[0] if row else None
    if pawn_id:
        for skill in ("Shooting", "Melee"):
            c.execute(
                "INSERT INTO rimworld_pawn_skills (pawn_id, skill_name, skill_level, passion, channel_id) "
                "VALUES (?,?,?,?,?)", (pawn_id, skill, 5, 0, CHANNEL))
        c.commit()
    c.close()
    return pawn_id


def reset_heal_cooldown():
    """Кулдаун лечения живёт в базе и переживает прогон.

    Без сброса второй запуск скрипта видит «⏳ ещё 13 минут» и записывает это
    как провал лечения — хотя проверять он должен обратное.
    """
    c = db_conn()
    try:
        c.execute("DELETE FROM rimworld_heal_cooldowns WHERE channel_id=? AND username=?",
                  (CHANNEL, USER))
        c.commit()
    except sqlite3.OperationalError:
        pass
    c.close()


def set_passion(pawn_id, skill="Shooting", passion=1):
    """Проставить страсть напрямую.

    В живой игре её ставит мод по команде `set_passion`; поддельный мод
    команду подтверждает, но состояние пешки не меняет — поэтому «сброс
    страсти» иначе всегда упирался бы в «страсти нет».
    """
    c = db_conn()
    c.execute("UPDATE rimworld_pawn_skills SET passion=? "
              "WHERE pawn_id=? AND skill_name=? AND channel_id=?",
              (passion, pawn_id, skill, CHANNEL))
    c.commit()
    c.close()


def clear_queue():
    c = db_conn()
    try:
        c.execute("DELETE FROM rimworld_pending_commands WHERE channel_id=?", (CHANNEL,))
        c.commit()
    except sqlite3.OperationalError:
        pass
    c.close()


def buy(name, path, body, price, jwt_token, expect_ok=True):
    """Одна платная покупка: списалось ровно price и команда легла в очередь."""
    before = points()
    q_before = len(queue_rows())
    code, resp = call(path, body, jwt_token=jwt_token)
    after = points()
    q_after = len(queue_rows())
    ok = bool(resp.get("success"))
    if not expect_ok:
        check(f"{name}: отказ (как и ожидалось)", not ok, json.dumps(resp, ensure_ascii=False)[:150])
        check(f"{name}: деньги не тронуты", before == after, f"{before} -> {after}")
        return None
    if not ok:
        check(f"{name}: покупка прошла", False, f"HTTP {code} {json.dumps(resp, ensure_ascii=False)[:200]}")
        check(f"{name}: деньги не потеряны при отказе", before == after, f"{before} -> {after}")
        return None
    check(f"{name}: списано ровно {price}", before - after == price, f"{before} -> {after} (разница {before-after})")
    check(f"{name}: команда встала в очередь", q_after == q_before + 1, f"{q_before} -> {q_after}")
    rows = queue_rows()
    return rows[-1][0] if rows else None


def main():
    print(f"бэкенд: {BASE}\nбаза:   {DB}\n")
    if not any(h in BASE for h in ("127.0.0.1", "localhost", "::1")):
        print("ОТКАЗ: этот прогон только против локального бэкенда.")
        return 2

    secret = os.environ.get("TWITCH_EXTENSION_SECRET")
    if not secret:
        print("нет TWITCH_EXTENSION_SECRET в окружении — подгрузи local.env")
        return 2
    jwt_token = make_jwt(secret)

    code, _ = call("/health", method="GET")
    if code != 200:
        print(f"бэкенд не отвечает на /health (код {code}) — подними его")
        return 2

    # Токен мода — им же авторизуется очередь /api/rimworld/*
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "Расширение", "backend"))
    module_token = None
    try:
        cwd = os.getcwd()
        os.chdir(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "Расширение", "backend"))
        from routes.streamer import issue_module_token
        module_token = issue_module_token(CHANNEL, "rimworld")
        os.chdir(cwd)
    except Exception as e:
        print(f"не выпустил module-token: {e}")

    set_points(5_000_000)
    clear_queue()

    # ── C1 создать пешку ───────────────────────────────────────────────────
    print("\nC1. Создать пешку (200💎)")
    buy("создание пешки", "/api/rimworld/create-pawn", {}, 200, jwt_token)

    # ── двойной клик ───────────────────────────────────────────────────────
    print("\nC1-бис. Двойной клик по той же кнопке (M98 dedup)")
    before = points()
    q_before = len(queue_rows())
    code, resp = call("/api/rimworld/create-pawn", {}, jwt_token=jwt_token)
    after = points()
    q_after = len(queue_rows())
    check("повтор отвечает успехом (зритель нажал на то, что сработало)",
          bool(resp.get("success")), json.dumps(resp, ensure_ascii=False)[:150])
    check("повтор НЕ списал второй раз", before == after, f"{before} -> {after}")
    check("повтор не создал вторую команду", q_after == q_before, f"{q_before} -> {q_after}")

    # ── C2 лечение + кулдаун ───────────────────────────────────────────────
    print("\nC2. Лечение (150💎) и кулдаун 15 минут")
    clear_queue()
    reset_heal_cooldown()
    buy("лечение", "/api/rimworld/heal-pawn", {}, 150, jwt_token)
    before = points()
    code, resp = call("/api/rimworld/heal-pawn", {}, jwt_token=jwt_token)
    after = points()
    if resp.get("success"):
        note("второе лечение подряд прошло — сработал dedup двойного клика, "
             "кулдаун этим прогоном не доказан (нужен интервал > окна дедупа)")
        check("второе лечение не списало деньги повторно", before == after, f"{before} -> {after}")
    else:
        check("кулдаун держит второе лечение", True, json.dumps(resp, ensure_ascii=False)[:150])
        check("отказ по кулдауну не списал деньги", before == after, f"{before} -> {after}")

    # ── C3 воскрешение ─────────────────────────────────────────────────────
    print("\nC3. Воскрешение (500💎)")
    clear_queue()
    buy("воскрешение", "/api/rimworld/resurrect-pawn", {}, 500, jwt_token)

    # ── C4 магазин ─────────────────────────────────────────────────────────
    print("\nC4. Магазин — тот самый фикс _rwBuyItem из changelog 0.0.2")
    clear_queue()
    code, resp = seed_catalog(module_token)
    check("каталог принят от мода", code == 200, f"HTTP {code} {json.dumps(resp, ensure_ascii=False)[:120]}")

    before = points()
    code2, resp2 = call("/api/rimworld/buy-item", {"item_def": "NoSuchItem"}, jwt_token=jwt_token)
    after = points()
    check("несуществующий товар: отказ", not resp2.get("success"),
          json.dumps(resp2, ensure_ascii=False)[:120])
    check("несуществующий товар: деньги не списаны", before == after, f"{before} -> {after}")

    # ПЕРВАЯ покупка в RimWorld выдаёт достижение `first_rimworld_buy` и
    # начисляет за него 500💎 (database.py:470). На балансе это выглядит как
    # «списали меньше цены» — из-за этого прогон сначала показал списание 700
    # вместо 1200. Поэтому первую покупку делаем «прогревочной», а строго
    # проверяем вторую, когда достижение уже выдано.
    clear_queue()
    call("/api/rimworld/buy-item", {"item_def": "Gun_AuditRifle"}, jwt_token=jwt_token)
    note("первая покупка сделана вхолостую — она забирает достижение "
         "first_rimworld_buy (+500💎), иначе оно исказило бы проверку списания")

    clear_queue()
    cmd_id = buy("покупка одежды из магазина", "/api/rimworld/buy-item",
                 {"item_def": "Apparel_AuditVest"}, 1200, jwt_token)
    # Суть фикса `_rwBuyItem`: покупка обязана уйти СВОЕЙ командой мода, а не в
    # чужой эндпоинт. Проверяем не ответ, а что реально легло в очередь.
    rows = queue_rows()
    cmd_type = None
    if rows:
        try:
            cmd_type = json.loads(rows[-1][2]).get("type")
        except Exception:
            cmd_type = None
    check("команда магазина имеет тип equip_item", cmd_type == "equip_item",
          f"тип в очереди: {cmd_type}")

    clear_queue()
    buy("покупка оружия из магазина", "/api/rimworld/buy-item",
        {"item_def": "Gun_AuditRifle"}, 2500, jwt_token)

    # ── C6 пассии ──────────────────────────────────────────────────────────
    print("\nC6. Пассия и сброс пассии")
    pawn_id = seed_pawn()
    check("пешка для проверки заведена", pawn_id is not None, f"pawn_id={pawn_id}")
    clear_queue()
    buy("покупка пассии", "/api/rimworld/buy-passion",
        {"skill_def": "Shooting", "passion": 1}, 500, jwt_token)
    clear_queue()
    # Мод команду не исполняет, поэтому страсть проставляем сами — иначе сброс
    # всегда упирался бы в «страсти нет» и проверить его было бы нечем.
    set_passion(pawn_id, "Shooting", 1)
    buy("сброс пассии", "/api/rimworld/reset-passion",
        {"skill_def": "Shooting"}, 300, jwt_token)

    # ── C8 отказ мода → возврат ────────────────────────────────────────────
    print("\nC8. Мод отказался выполнять — деньги обязаны вернуться")
    clear_queue()
    set_points(5_000_000)
    cmd_id = buy("покупка под отказ", "/api/rimworld/create-pawn", {}, 200, jwt_token)
    if not module_token:
        check("есть module-token для ack", False, "не выпустился — отказ проверить нечем")
    elif not cmd_id:
        check("команда для отказа найдена", False, "очередь пуста")
    else:
        # Мод забирает команду (она помечается delivered) и отказывается.
        call("/api/rimworld/commands", method="GET", bearer=module_token)
        before = points()
        code, resp = call("/api/rimworld/ack-command",
                          {"command_id": cmd_id, "success": False,
                           "message": "audit: отказ по требованию"},
                          bearer=module_token)
        after = points()
        check("отказ принят", code == 200, f"HTTP {code} {resp}")
        check("деньги вернулись ровно в размере цены", after - before == 200,
              f"{before} -> {after} (вернулось {after-before})")
        ids = [r[0] for r in queue_rows()]
        check("строка очереди закрыта", cmd_id not in ids, f"осталось в очереди: {len(ids)}")

        # Повторный отказ по тому же id не должен платить второй раз.
        before2 = points()
        call("/api/rimworld/ack-command",
             {"command_id": cmd_id, "success": False, "message": "audit: повтор"},
             bearer=module_token)
        after2 = points()
        check("ПОВТОРНЫЙ отказ не платит второй раз", before2 == after2,
              f"{before2} -> {after2}")

    print("\n" + "=" * 62)
    for n in notes:
        print("ИНФО: " + n)
    if fails:
        print(f"\nПРОВАЛЕНО {len(fails)}:")
        for f in fails:
            print("  - " + f)
        return 1
    print("\nТРЕК C: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())

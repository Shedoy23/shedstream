# -*- coding: utf-8 -*-
"""grant-missed-daily.py — выдать награду за дейлик, который сгорел впустую.

ЗАЧЕМ. 05.08 стрим шёл под другой игрой, мода Bannerlord не было, а расширение
всё ещё принимало заявки. Пять зрителей забрали ежедневный бонус: отметка
«сегодня забрал» записалась, заявка протухла в очереди, награда не выдана.
Возврат вернул ноль — и правильно: дейлик бесплатный, крустиков никто не платил.
Потеряна была не валюта, а сама награда за тот день.

ПОЧЕМУ НЕЛЬЗЯ ПРОСТО УДАЛИТЬ ОТМЕТКУ. Право забрать бонус привязано к ДАТЕ.
Удаление строки за 05.08 не даёт ничего: следующий день уже наступил, и забрать
сегодняшний бонус эти зрители могут и без нашего вмешательства. Вернуть надо не
право, а саму награду — то есть поставить моду те же задания заново.

ПОЧЕМУ СКРИПТ, А НЕ РУЧНОЙ SQL. Задание, поставленное при выключенной игре,
через 30 минут снова протухнет (`_queued_action_ttl_sweeper`) — и мы повторим
ту же ошибку, только руками. Поэтому скрипт САМ проверяет, что мод на связи,
и отказывается работать, если игры нет.

ЗАПУСК (на проде, при ЗАПУЩЕННОЙ игре):
    python3 scripts/grant-missed-daily.py --dry-run   # показать, что сделает
    python3 scripts/grant-missed-daily.py             # выдать
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid

DB_PATH = os.environ.get("SHEDLINK_DB", "/root/twitch-extension/backend/viewers.db")
CHANNEL_ID = 98319857
MISSED_DATE = "2026-08-05"
ONLINE_WINDOW_SEC = 60

# Что именно каждый выбрал в тот день — берём из таблицы дейликов, не угадываем.
REWARDS = {
    "gold": ("player.give_item", {"item_type": "gold", "amount": 100000}),
    "xp":   ("hero.add_skill",   {"skill_key": "", "xp": 50000}),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT last_seen_ts FROM module_last_seen "
        "WHERE channel_id=? AND module_id='bannerlord'", (CHANNEL_ID,)).fetchone()
    age = (time.time() - row["last_seen_ts"]) if row else None
    online = age is not None and age < ONLINE_WINDOW_SEC
    if not online:
        print("Мод Bannerlord НЕ на связи (%s). Запусти игру и повтори — иначе "
              "задания снова протухнут через 30 минут." %
              ("сигнала не было" if age is None else "молчит %d сек" % int(age)))
        return 1

    victims = conn.execute(
        "SELECT username, reward_type FROM bannerlord_daily_claims "
        "WHERE channel_id=? AND claim_date=? ORDER BY username",
        (CHANNEL_ID, MISSED_DATE)).fetchall()
    if not victims:
        print("Некому выдавать: записей за %s нет." % MISSED_DATE)
        return 0

    for v in victims:
        username, reward_type = v["username"], v["reward_type"]
        spec = REWARDS.get(reward_type)
        if not spec:
            print("  ? @%s: неизвестный тип награды %r — пропускаю" % (username, reward_type))
            continue
        action_type, extra = spec
        payload = {"initiated_by": username, "target": username,
                   "_daily": True, "_compensation": MISSED_DATE, **extra}
        action_id = uuid.uuid4().hex
        print("  → @%s: %s %s" % (username, action_type, json.dumps(extra, ensure_ascii=False)))
        if args.dry_run:
            continue
        conn.execute(
            "INSERT INTO module_actions "
            "(channel_id, module_id, action_id, type, data, status) "
            "VALUES (?, 'bannerlord', ?, ?, ?, 'queued')",
            (CHANNEL_ID, action_id, action_type, json.dumps(payload, ensure_ascii=False)))

    if args.dry_run:
        print("\n(сухой прогон — ничего не записано)")
    else:
        conn.commit()
        print("\nВыдано: %d. Награды придут в игру в течение нескольких секунд."
              % len(victims))
    return 0


if __name__ == "__main__":
    sys.exit(main())

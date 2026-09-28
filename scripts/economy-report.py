#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""economy-report.py — откуда зрители брали крустики за стрим-день.

ЗАЧЕМ. 2026-08-23 числа баланса дважды подбирались на глаз, и оба раза
владелец поправлял их по памяти о своих стримах. Спорить о числах без данных
дорого: каждая итерация — деплой и ожидание следующего эфира. Этот отчёт
показывает факт, чтобы на пост-стрим-триаже подкручивать по нему.

ЧТО ПОКАЗЫВАЕТ.
  1. Разбивку дохода по источникам: разговор, просмотр со вниманием, просмотр
     «вкладка открыта», квесты.
  2. Кто из зрителей на чём живёт — видно, поощряет ли экономика тех, кого
     хотели поощрять.
  3. Долю пассива: сколько платформа заплатила за то, что человек просто не
     закрыл вкладку.

ЗАПУСК (на проде):
    /root/twitch-extension/venv/bin/python scripts/economy-report.py \
        --db backend/viewers.db --day 2026-08-24

Без --day берётся последний день, за который вообще есть начисления.

Коды возврата: 0 — отчёт построен, 2 — данных за день нет.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

SOURCES = {
    "chat":       "разговор",
    "watch_full": "просмотр со вниманием",
    "watch_half": "вкладка открыта",
    "quest":      "квесты",
}


def _bar(part: int, whole: int, width: int = 24) -> str:
    if whole <= 0:
        return ""
    filled = int(round(width * part / whole))
    return "█" * filled + "·" * (width - filled)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="backend/viewers.db")
    ap.add_argument("--day", default="", help="YYYY-MM-DD; по умолчанию последний с данными")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    # База без миграции m117 — обычное дело для локальной копии. Понятное
    # сообщение вместо трассировки: иначе выглядит как поломка продукта, хотя
    # это ошибка запуска (тот же класс, что записан про SelfTest в DEFERRED).
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='points_income'"
    ).fetchone()
    if not exists:
        print(f"В базе {args.db} нет таблицы points_income.")
        print("Она появляется миграцией M117 при старте бэкенда — значит эта база")
        print("либо старая, либо локальная копия без миграций. Отчёта не будет.")
        return 2

    day = args.day
    if not day:
        row = conn.execute("SELECT MAX(day) FROM points_income").fetchone()
        day = row[0] if row and row[0] else ""
    if not day:
        print("Данных о доходах нет вообще — таблица points_income пуста.")
        print("Она наполняется во время эфира; до первого стрима это норма.")
        return 2

    rows = conn.execute(
        "SELECT source, SUM(points), SUM(events) FROM points_income "
        "WHERE day = ? GROUP BY source", (day,)
    ).fetchall()
    if not rows:
        print(f"За {day} начислений нет.")
        return 2

    total = sum(r[1] for r in rows)
    print(f"\n=== Откуда крустики, {day} ===\n")
    print(f"{'источник':24} {'крустиков':>10} {'доля':>6}  {'начислений':>10}")
    for source, pts, events in sorted(rows, key=lambda r: -r[1]):
        name = SOURCES.get(source, source)
        share = 100.0 * pts / total if total else 0
        print(f"{name:24} {pts:>10} {share:>5.1f}%  {events:>10}  {_bar(pts, total)}")
    print(f"{'ИТОГО':24} {total:>10}")

    passive = sum(r[1] for r in rows if r[0] == "watch_half")
    talk = sum(r[1] for r in rows if r[0] == "chat")
    print()
    print(f"За открытую вкладку заплачено: {passive} ({100.0*passive/total:.1f}% всего)")
    print(f"За разговор:                   {talk} ({100.0*talk/total:.1f}% всего)")
    if talk and passive:
        print(f"Разговор к пассиву: {talk/passive:.2f}× "
              f"({'болтуны впереди' if talk > passive else 'пассив всё ещё выгоднее'})")

    print(f"\n=== Кто на чём живёт (топ {args.top}) ===\n")
    people = conn.execute(
        "SELECT username, SUM(points) AS total FROM points_income "
        "WHERE day = ? GROUP BY username ORDER BY total DESC LIMIT ?",
        (day, args.top),
    ).fetchall()
    header = f"{'зритель':20} {'всего':>8}"
    for s in SOURCES:
        header += f" {SOURCES[s][:9]:>10}"
    print(header)
    for username, ptotal in people:
        by = dict(conn.execute(
            "SELECT source, SUM(points) FROM points_income "
            "WHERE day = ? AND username = ? GROUP BY source", (day, username)
        ).fetchall())
        line = f"{username[:20]:20} {ptotal:>8}"
        for s in SOURCES:
            line += f" {by.get(s, 0):>10}"
        print(line)

    print("\nЧисла — это регулятор. Если разговор проигрывает пассиву, крутить")
    print("надо CHAT_BONUS_* и награды чат-квестов, а не потолок.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

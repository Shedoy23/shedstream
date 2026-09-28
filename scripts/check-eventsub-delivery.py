#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-eventsub-delivery.py — не молчит ли Twitch про фолловеров.

ЗАЧЕМ. 2026-08-05 Twitch перестал присылать `channel.follow`, продолжая
присылать всё остальное. Ничего не упало: подписка так и числилась `enabled`,
ошибок в логе не было, мониторинг «сервис жив» ничего не заметил. Пропажу
обнаружили через 17 дней, и только потому, что владелец спросил.

Класс проблемы — ТИХАЯ ДЕГРАДАЦИЯ ВНЕШНЕЙ ЗАВИСИМОСТИ: её нельзя поймать
проверкой «мы живы», её ловит только сверка факта с ожиданием. Здесь факт —
сколько фолловеров реально прибавилось по данным Twitch; ожидание — сколько
событий `channel.follow` мы приняли.

ОКНО ЖЁСТКО 24 ЧАСА. Считаем принятые события по таблице `eventsub_seen`, а у
неё TTL ровно сутки (`cleanup_seen_loop`). На окне шире сравнение врёт: старые
события уже удалены, и здоровая система выглядела бы сломанной.

Коды возврата: 0 — сходится (или сверять нечего), 1 — расхождение,
2 — проверить не удалось (нет токена, Twitch недоступен). 2 — это НЕ «всё
хорошо»: неизвестность не считается успехом.

Запуск на проде:
    /root/twitch-extension/venv/bin/python scripts/check-eventsub-delivery.py \
        --db backend/viewers.db

Проверка самого скрипта (без сети и базы):
    python scripts/check-eventsub-delivery.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

WINDOW_SEC = 24 * 3600
EVENT = "channel.follow"


def verdict(followers_gained: int, events_seen: int) -> tuple[int, str]:
    """Чистое решение, отделённое от сети и базы — его и проверяет --self-test.

    Возвращает (код возврата, человеческая строка).
    """
    if followers_gained == 0:
        return 0, "за сутки фолловеров не было — сверять нечего"
    if events_seen >= followers_gained:
        return 0, "фолловеров %d, событий принято %d — сходится" % (
            followers_gained, events_seen,
        )
    return 1, (
        "фолловеров %d, а событий принято только %d — Twitch не досылает "
        "channel.follow. Пересоздать подписку и проверить живым фолловом "
        "(см. DEFERRED.md и RUNBOOK §6 «Проверки»)." % (followers_gained, events_seen)
    )


def _app_token(client_id: str, client_secret: str) -> str:
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request("https://id.twitch.tv/oauth2/token", data=body)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["access_token"]


def followers_gained(client_id: str, user_token: str, broadcaster_id: str,
                     now: float) -> int:
    """Сколько человек зафолловили за последние сутки (по данным Twitch)."""
    url = "https://api.twitch.tv/helix/channels/followers?" + urllib.parse.urlencode(
        {"broadcaster_id": broadcaster_id, "first": "100"}
    )
    req = urllib.request.Request(url, headers={
        "Client-Id": client_id, "Authorization": "Bearer " + user_token,
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    cutoff = now - WINDOW_SEC
    count = 0
    for row in data.get("data", []):
        stamp = (row.get("followed_at") or "").replace("Z", "+00:00")
        try:
            when = datetime.fromisoformat(stamp).timestamp()
        except ValueError:
            continue
        if when >= cutoff:
            count += 1
    return count


def events_seen(db_path: str, channel_id: int, now: float) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT count(*) FROM eventsub_seen "
            "WHERE event_type = ? AND channel_id = ? AND seen_at >= ?",
            (EVENT, channel_id, now - WINDOW_SEC),
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def self_test() -> int:
    """Показать решающую функцию в ОБОИХ состояниях, а не только в зелёном."""
    cases = [
        ((0, 0), 0, "нет фолловеров"),
        ((3, 3), 0, "всё доставлено"),
        ((3, 5), 0, "событий больше (ретраи) — не повод паниковать"),
        ((1, 0), 1, "ровно наш случай 20 августа: фоллов был, события нет"),
        ((5, 2), 1, "часть теряется"),
    ]
    bad = 0
    for (gained, seen), want, name in cases:
        got, text = verdict(gained, seen)
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] %-52s код=%d  %s" % (
            "ok" if ok else "СЛОМАНО", name, got, text[:60]))
    print("self-test: %s" % ("все случаи верны" if not bad else "%d СЛОМАНО" % bad))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="backend/viewers.db")
    ap.add_argument("--channel-id", type=int, default=0,
                    help="по умолчанию берётся TWITCH_BROADCASTER_ID из .env")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    sys.path.insert(0, os.path.join(os.path.dirname(args.db) or ".", ""))
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(args.db)), ".env"))
    except ImportError:
        pass

    client_id = os.getenv("TWITCH_CLIENT_ID", "")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")
    channel_id = args.channel_id or int(os.getenv("TWITCH_BROADCASTER_ID", "0") or 0)
    if not (client_id and client_secret and channel_id):
        print("НЕ ПРОВЕРЕНО: нет TWITCH_CLIENT_ID/SECRET или channel_id")
        return 2

    # Список фолловеров требует ПОЛЬЗОВАТЕЛЬСКОГО токена со scope
    # moderator:read:followers — он лежит в базе зашифрованным.
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(args.db)))
        from database import _decrypt_secret  # type: ignore
        conn = sqlite3.connect(args.db)
        row = conn.execute(
            "SELECT oauth_access_token FROM channels WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()
        conn.close()
        user_token = _decrypt_secret(row[0]) if row and row[0] else ""
    except Exception as e:
        print("НЕ ПРОВЕРЕНО: не удалось получить токен вещателя: %s" % e)
        return 2
    if not user_token:
        print("НЕ ПРОВЕРЕНО: у канала %d нет OAuth-токена" % channel_id)
        return 2

    now = time.time()
    try:
        gained = followers_gained(client_id, user_token, str(channel_id), now)
    except Exception as e:
        print("НЕ ПРОВЕРЕНО: Twitch не ответил: %s" % e)
        return 2
    try:
        seen = events_seen(args.db, channel_id, now)
    except Exception as e:
        print("НЕ ПРОВЕРЕНО: база недоступна: %s" % e)
        return 2

    code, text = verdict(gained, seen)
    print(("OK: " if code == 0 else "РАСХОЖДЕНИЕ: ") + text)
    return code


if __name__ == "__main__":
    sys.exit(main())

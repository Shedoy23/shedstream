# -*- coding: utf-8 -*-
"""Считает скачивания Manager из журнала nginx и кладёт их в воронку.

ЗАЧЕМ. `manager_downloaded` — первая ступень воронки (ROADMAP §R4), и собрать
её приложением нельзя: в момент скачивания Manager ещё не запущен. Единственный,
кто это видит, — веб-сервер, отдающий файл. Пока Manager нигде не лежал, ступень
была недостижима; 2026-08-20 он опубликован, и она стала считаемой.

Что этот счёт МОЖЕТ и чего НЕ может:

  может — сказать, сколько раз файл скачали и как это соотносится с числом
  запусков. Разрыв между «скачал» и «запустил» — первая точка отвала, и там
  стоит неподписанный exe с предупреждением Windows;

  НЕ может — связать скачивание с конкретной установкой. У скачивания нет
  installation_id, он появляется только при первом запуске. Поэтому первая
  ступень воронки считается «сколько раз», а не «сколько людей», и складывать
  её с остальными как одну шкалу нельзя.

РОБОТЫ (2026-09-01). Из десяти последних скачиваний девять сделали краулеры:
Amazonbot, MJ12bot, LohiSoftBot и сканеры с подставным iPhone-User-Agent. Раньше
скрипт брал только время, путь и код ответа — отличить робота от человека он не
мог в принципе, и первая ступень воронки врала в плюс. Теперь известные роботы
отсеиваются по подписи браузера, а сколько их было — печатается: **число
отсеянных и есть мера доверия к этой ступени**. Сканеры, притворяющиеся
браузером, проходят и будут проходить — по подписи их не отличить. Строка без
подписи засчитывается: потерять живого человека хуже, чем пропустить робота.
Гейт — `backend/tests/test_download_ingest_bots.py`.

ПРИВАТНОСТЬ. IP-адреса не сохраняются и вообще не покидают эту функцию: из
строки журнала берутся только факт успешной отдачи и время. Подпись браузера
читается для отсева роботов и тоже никуда не пишется.

ЗАПУСК (на сервере):
    python3 scripts/ingest-download-events.py --db /root/twitch-extension/backend/viewers.db

Идемпотентность: прогресс хранится рядом с БД в `.download-ingest-state`,
обрабатываются только записи СТРОГО НОВЕЕ последней обработанной. Повторный
запуск ничего не удваивает; пропущенная ротация журнала может потерять
несколько записей — для метрики первой ступени это приемлемо, а вот двойной
счёт исказил бы вывод.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import os
import re
import sqlite3
import sys
from datetime import datetime

# 84.17.46.76 - - [20/Aug/2026:03:19:19 +0000] "GET /releases/X.zip HTTP/1.1" 200 67853805 ...
LINE = re.compile(
    r'\[(?P<when>[^\]]+)\]\s+"(?P<method>[A-Z]+)\s+(?P<path>\S+)[^"]*"\s+(?P<status>\d{3})')

TIME_FORMAT = "%d/%b/%Y:%H:%M:%S %z"

# Подпись браузера — последнее поле в кавычках. Отсутствует в укороченных
# форматах журнала; тогда строку засчитываем (см. докстринг).
USER_AGENT = re.compile(r'"([^"]*)"\s*$')

# Отсев по подписи. Список из того, что реально приходило на shedoy23.ru, плюс
# общие маркеры. Сравнение по вхождению в нижнем регистре: подписи роботов
# меняют версии, но не самоназвание.
BOT_MARKERS = (
    "bot", "crawler", "spider", "slurp", "scrapy", "curl", "wget",
    "python-requests", "libwww", "httpclient", "headlesschrome",
    "ahrefs", "semrush", "mj12", "dataprovider", "lohisoft",
    "facebookexternalhit", "petalbot", "bytespider", "gptbot",
)

# Сколько отсеяно за прогон. Печатается в конце: это мера того, насколько
# верхней ступени воронки вообще можно верить.
bots_skipped = 0


def looks_like_bot(agent: str) -> bool:
    low = (agent or "").lower()
    return any(marker in low for marker in BOT_MARKERS)


def parse_line(line: str):
    m = LINE.search(line)
    if not m:
        return None
    if m.group("method") != "GET":
        return None                      # HEAD и проверки — не скачивания
    if m.group("status") not in ("200", "206"):
        return None                      # 404 и обрывы не считаем
    path = m.group("path").split("?", 1)[0]
    if not path.startswith("/releases/") or "Manager" not in path:
        return None
    ua = USER_AGENT.search(line.rstrip())
    if ua and looks_like_bot(ua.group(1)):
        global bots_skipped
        bots_skipped += 1
        return None                      # краулер — это не «до нас дошли»
    try:
        when = datetime.strptime(m.group("when"), TIME_FORMAT)
    except ValueError:
        return None
    return when.timestamp(), os.path.basename(path)


def log_files(pattern: str):
    """Свежие файлы журнала последними, чтобы прогресс двигался вперёд."""
    files = sorted(glob.glob(pattern), reverse=True)     # access.log.2, .1, access.log
    return files


def read_lines(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", errors="replace") as handle:
        for line in handle:
            yield line


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--logs", default="/var/log/nginx/access.log*")
    parser.add_argument("--state", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    state_path = args.state or (args.db + ".download-ingest-state")
    last_seen = 0.0
    if os.path.exists(state_path):
        try:
            last_seen = float(open(state_path).read().strip() or 0)
        except ValueError:
            last_seen = 0.0

    found = []
    for path in log_files(args.logs):
        try:
            for line in read_lines(path):
                parsed = parse_line(line)
                if parsed and parsed[0] > last_seen:
                    found.append(parsed)
        except OSError as exc:
            print("не смог прочитать %s: %s" % (path, exc), file=sys.stderr)

    found.sort()
    if not found:
        print("новых скачиваний нет (последняя обработанная отметка: %s); "
              "роботов отсеяно: %d"
              % ((datetime.fromtimestamp(last_seen) if last_seen else "нет"),
                 bots_skipped))
        return 0

    print("новых скачиваний: %d (роботов отсеяно: %d)" % (len(found), bots_skipped))
    if args.dry_run:
        for when, name in found[:10]:
            print("  %s  %s" % (datetime.fromtimestamp(when), name))
        return 0

    conn = sqlite3.connect(args.db)
    try:
        for when, name in found:
            conn.execute(
                "INSERT INTO onboarding_events "
                "(event, integration_version, source_step, created_at) "
                "VALUES ('manager_downloaded', ?, 'nginx', ?)",
                (name[:120], when))
        conn.commit()
    finally:
        conn.close()

    with open(state_path, "w") as handle:
        handle.write("%.6f" % found[-1][0])
    print("записано в воронку: %d, отметка сдвинута на %s"
          % (len(found), datetime.fromtimestamp(found[-1][0])))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Длительность боёв по размеру: лог автопилота + лог мода (26.09.2026).

Нужен, чтобы сравнивать настройки боевого ИИ (RBM) по цифрам, а не на глаз.
Начало боя — «БОЙ: боевой автопилот добавлен», конец — «БОЙ: результат
определён»; размер боя берётся из ближайшей строки выплаты мода
([BattlePayout v2] ... enemies=N, есть с 21.09). Осады не считаются.

    python scripts/battle-durations.py 20260925 20260926
"""
import os
import re
import statistics
import sys
from collections import defaultdict

ROOT = os.path.expanduser("~/Documents/Mount and Blade II Bannerlord")
BUCKETS = ["<50", "50-199", "200-499", "500+"]


def secs(stamp):
    h, m, s = stamp.split(":")
    return int(h) * 3600 + int(m) * 60 + int(float(s))


def bucket(enemies):
    return "<50" if enemies < 50 else "50-199" if enemies < 200 else "200-499" if enemies < 500 else "500+"


def day_stats(day):
    ap = os.path.join(ROOT, "Logs", f"autopilot_{day}.txt")
    ml = os.path.join(ROOT, "Configs", "ModLogs", f"bannerlordlink_{day}.txt")
    if not (os.path.exists(ap) and os.path.exists(ml)):
        return None
    ends = {}
    with open(ml, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r"\[(\d\d:\d\d:\d\d)[.\d]*\] \[BattlePayout v2\] battle=(\w+) @\S+ enemies=(\d+) siege=(\w+)", line)
            if m and m[2] not in ends:
                ends[m[2]] = (secs(m[1]), int(m[3]), m[4] == "True")
    events = sorted(ends.values())
    result = defaultdict(list)
    start = None
    with open(ap, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r"(\d\d:\d\d:\d\d)", line)
            if not m:
                continue
            t = secs(m[1])
            if "БОЙ: боевой автопилот добавлен" in line and start is None:
                start = t
            elif "БОЙ: результат определён" in line and start is not None:
                duration, start = t - start, None
                near = [e for e in events if abs(e[0] - t) <= 40]
                if near and not near[0][2] and 0 < duration < 3600:
                    result[bucket(near[0][1])].append(duration)
    return result


def main(days):
    for day in days:
        stats = day_stats(day)
        if stats is None:
            print(f"{day}: нет логов")
            continue
        parts = [f"{b}: {len(stats[b])} боёв, медиана {statistics.median(stats[b]):.0f} с, макс {max(stats[b])} с"
                 for b in BUCKETS if stats[b]]
        print(f"{day}  " + ("; ".join(parts) or "боёв с размером нет"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or []))

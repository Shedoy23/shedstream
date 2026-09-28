# -*- coding: utf-8 -*-
"""balance-report.py — баланс классов Bannerlord ПО ЛОГАМ, а не по ощущению.

ЗАЧЕМ. Лестница наград (KILL_STREAKS / LADDER_SCALE) была выведена рассуждением
и записана в код как факт: «рядовой пехотинец ≈ 100 HP → убить его ≈ 18 очков,
отсюда LADDER_SCALE = 18». Разумно — но это ПРЕДПОЛОЖЕНИЕ, и с момента
написания оно ни разу не сверялось с реальностью, хотя логи лежали рядом.
2026-08-03 первая же сверка показала: 18 участий из 122 дают ровно ноль.

Баланс — не задача «сесть и продумать», а ЦИКЛ: данные → правка → снова данные.
Этот скрипт закрывает первую половину цикла и делает её повторяемой: после
каждой правки прогнать заново и сравнить.

ЧТО СЧИТАЕТ (на класс): участия, средний и медианный заработок за бой, доля
участий с НУЛ�енм, убийства, урон, поглощение, смерти, вехи вклада.

ЧЕГО НЕ СКАЖЕТ: весело ли на классе играть. Это только владелец и чат.

⚠️ ОГОВОРКА О КЛАССАХ. Класс берётся ТЕКУЩИЙ (из прод-базы), а логи —
исторические. Зритель, сменивший класс, во всех старых боях будет посчитан по
новому. Поэтому по умолчанию берём только логи с 2026-07-21 — с момента, когда
появилась система вкладов; чем свежее окно, тем меньше искажение.

ЗАПУСК:
    python scripts/balance-report.py                # окно по умолчанию
    python scripts/balance-report.py --since 20260801
    python scripts/balance-report.py --classes classes.tsv

Файл классов — TSV «ник<TAB>класс». Снять с прода:
    sqlite3 viewers.db "SELECT username||char(9)||class_key FROM
        bannerlord_hero_class WHERE channel_id=<id>;"

ИГРУ И ПРОД НЕ ТРОГАЕТ: только чтение локальных логов.
"""
import argparse
import os
import re
import statistics
import sys
from collections import defaultdict

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

LOG_DIR_DEFAULT = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    "Documents", "Mount and Blade II Bannerlord", "Configs", "ModLogs")

# [CONTRIB итог] @ник: киллы=7 урон=640 поглощено=1324 (СГОРЕЛО — умирал) очки=288 вех=3 заработал=41720💰
RE_TOTAL = re.compile(
    r"\[CONTRIB итог\] @(?P<user>[^\s:]+):\s*"
    r"киллы=(?P<kills>\d+)\s+"
    r"урон=(?P<dmg>\d+)\s+"
    r"поглощено=(?P<abs>\d+)"
    r"(?P<burned>[^о]*СГОРЕЛО[^о]*)?.*?"
    r"очки=(?P<pts>\d+)\s+вех=(?P<ms>\d+)\s+заработал=(?P<gold>\d+)")


def load_classes(path):
    m = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[0].strip():
                m[parts[0].strip().lower()] = parts[1].strip()
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=LOG_DIR_DEFAULT)
    ap.add_argument("--classes", default=None,
                    help="TSV ник<TAB>класс; без него — только сводка по никам")
    ap.add_argument("--since", default="20260721",
                    help="ГГГГММДД, по умолчанию с появления системы вкладов")
    args = ap.parse_args()

    classes = load_classes(args.classes) if args.classes else {}

    files = []
    for name in sorted(os.listdir(args.logs)):
        m = re.match(r"bannerlordlink_(\d{8})\.txt$", name)
        if m and m.group(1) >= args.since:
            files.append((m.group(1), os.path.join(args.logs, name)))
    if not files:
        print("Логов в окне не найдено: %s с %s" % (args.logs, args.since))
        return 2

    # class -> list of per-battle dicts
    rows = defaultdict(list)
    unknown = set()
    for day, path in files:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                mt = RE_TOTAL.search(line)
                if not mt:
                    continue
                user = mt.group("user").lower()
                cls = classes.get(user)
                if cls is None:
                    unknown.add(user)
                    cls = "?неизвестен"
                rows[cls].append({
                    "user": user, "day": day,
                    "kills": int(mt.group("kills")),
                    "dmg":   int(mt.group("dmg")),
                    "abs":   int(mt.group("abs")),
                    "pts":   int(mt.group("pts")),
                    "ms":    int(mt.group("ms")),
                    "gold":  int(mt.group("gold")),
                    "died":  bool(mt.group("burned")),
                })

    total_rows = sum(len(v) for v in rows.values())
    print("=" * 100)
    print("БАЛАНС КЛАССОВ ПО ЛОГАМ — %d боёв-участий, файлов %d, окно с %s"
          % (total_rows, len(files), args.since))
    print("=" * 100)
    if not total_rows:
        print("Строк [CONTRIB итог] не найдено — проверь окно и формат логов.")
        return 1

    hdr = ("%-14s %5s %6s %9s %9s %7s %7s %8s %8s %6s"
           % ("класс", "боёв", "людей", "средн.💰", "медиан💰", "нулей%",
              "смерт%", "урон/бой", "погл/бой", "килл"))
    print(hdr)
    print("-" * len(hdr))

    order = sorted(rows.items(), key=lambda kv: -len(kv[1]))
    for cls, rs in order:
        golds = [r["gold"] for r in rs]
        zeros = sum(1 for g in golds if g == 0)
        deaths = sum(1 for r in rs if r["died"])
        print("%-14s %5d %6d %9s %9s %6.0f%% %6.0f%% %8.0f %8.0f %6.2f" % (
            cls, len(rs), len({r["user"] for r in rs}),
            "{:,}".format(int(statistics.mean(golds))).replace(",", " "),
            "{:,}".format(int(statistics.median(golds))).replace(",", " "),
            zeros * 100.0 / len(rs),
            deaths * 100.0 / len(rs),
            statistics.mean([r["dmg"] for r in rs]),
            statistics.mean([r["abs"] for r in rs]),
            statistics.mean([r["kills"] for r in rs]),
        ))

    if unknown:
        print("\nНиков без класса в базе (учтены как «?неизвестен»): %s"
              % ", ".join(sorted(unknown)))

    print("\nЧИТАТЬ ТАК:")
    print("  нулей%  — доля боёв, где зритель не получил НИЧЕГО. Главный")
    print("            показатель «класс не окупается»: пришёл и зря.")
    print("  смерт%  — доля боёв, где поглощение сгорело из-за смерти.")
    print("            Для танка это прямой удар по его же источнику дохода.")
    print("  погл/бой — сколько класс принимает на себя. Танк должен быть выше")
    print("            всех, иначе он не выполняет свою роль.")
    print("\n⚠️ Класс взят ТЕКУЩИЙ; сменившие класс искажают историю — сужай окно")
    print("   --since, если нужна точность.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

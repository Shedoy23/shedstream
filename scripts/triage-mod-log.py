# -*- coding: utf-8 -*-
"""triage-mod-log.py — что мод Bannerlord сделал за запуск и что молча отвалилось.

    python scripts/triage-mod-log.py                  # свежий лог, последняя сессия
    python scripts/triage-mod-log.py --all-sessions   # все запуски в файле
    python scripts/triage-mod-log.py --file <путь>    # конкретный лог
    python scripts/triage-mod-log.py --set-baseline   # запомнить текущие числа как норму

ЗАЧЕМ. Патчи мода держатся на сигнатурах методов игры. Обновление Bannerlord
сдвигает сигнатуры, и патч, не нашедший цель, **пропускается молча**: игра
запускается, мод пишет «всё хорошо», а механика мертва. Это наш самый дорогой
класс дефектов — зритель платит, эффекта нет, в логе тишина.

Читать лог глазами каждый раз бессмысленно: в нём тысячи строк за эфир, а
интересны десять. Скрипт вытаскивает эти десять и, главное, **сравнивает с
записанной нормой**: было 19 применённых патчей — стало 14, вот эти пятеро не
нашли цель.

ВЕРДИКТ ПО КОДУ ВОЗВРАТА, а не по печати (`CLAUDE.md`):
    0 — норма совпала;
    1 — регресс: патчей меньше нормы, есть упавшие, или мод не достучался до
        бэкенда;
    2 — лог не найден (нечего разбирать).

ЧЕГО СКРИПТ НЕ ЗНАЕТ. Патч, который цель НАШЁЛ и применился, но из-за
изменившейся внутри логики делает не то, отсюда неотличим от здорового: в логе
он выглядит одинаково. Такое ловится только прогоном действий в игре
(`docs/TESTING_PLAYBOOK.md`). Скрипт закрывает ровно «молча не применилось».

ПОБОЧНО: версия ИГРЫ в лог не пишется. При переезде на новую версию это первое,
что хочется знать. Пока определяется руками (главное меню игры) — заведено как
задача в `DEFERRED.md`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    for _s in ("stdout", "stderr"):
        try:
            getattr(sys, _s).reconfigure(encoding="utf-8")
        except Exception:
            pass

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "scripts" / "mod-log-baseline.json"
LOG_DIR = Path.home() / "Documents" / "Mount and Blade II Bannerlord" / "Configs" / "ModLogs"

SESSION_START = re.compile(r"^\[[\d:.]+\]\s+(v[\d.]+)\s+OnSubModuleLoad")
PATCH_TOTALS = re.compile(r"Harmony patched \(id=[^)]+\):\s*ok=(\d+)\s+failed=(\d+)\s+skipped=(\d+)")
PATCH_SKIP = re.compile(r"Harmony patch SKIP \(safe-rollback\):\s*(\S+)")
PATCH_FAILED = re.compile(r"Harmony patch FAILED:\s*(.+)")
TARGET_RESOLVED = re.compile(r"\[([\w:.-]+)\]\s+target resolved:\s*(\S+)")
FIRED = re.compile(r"\[([\w:.-]+)\]\s+FIRED")

CONNECT_OK = "Backend connectivity: OK"
HANDSHAKE_OK = "Module API handshake: SUCCESS"
POLLER_OK = "ActionPoller started"

# Строки, которые сами по себе означают проблему.
#
# «Unhandled» как маркер НЕ годится: строка «Global crash hooks installed
# (AppDomain.UnhandledException + ...)» пишется при каждом здоровом запуске, и
# первая же проверка на живом логе объявила её необработанным исключением.
# Инструмент, который кричит на собственную стартовую строку, перестают читать.
# Ловим настоящий след падения — «UNHANDLED» в верхнем регистре мод пишет сам,
# плюс стандартный хвост стека .NET.
ALARM_MARKERS = (
    ("[CrashGuard]", "перехваченный краш"),
    ("БЕЗ ЯВНОГО ИСХОДА", "платное действие завершилось без явного исхода"),
    ("UNHANDLED EXCEPTION", "необработанное исключение"),
    ("   at ", "хвост стека исключения"),
    ("Harmony patch FAILED", "патч не встал"),
)

# Тревога, которая ОБЯЗАНА валить вердикт. Остальные — к сведению: например,
# перехваченный краш означает, что защита сработала, и это не повод краснеть.
FATAL_ALARMS = ("платное действие завершилось без явного исхода", "патч не встал")


def newest_log() -> Path | None:
    if not LOG_DIR.is_dir():
        return None
    logs = sorted(LOG_DIR.glob("bannerlordlink_*.txt"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def split_sessions(lines: list[str]) -> list[list[str]]:
    """Один файл = один день, а запусков игры за день может быть несколько."""
    sessions: list[list[str]] = []
    for line in lines:
        if SESSION_START.search(line):
            sessions.append([])
        if sessions:
            sessions[-1].append(line)
    return sessions or ([lines] if lines else [])


def analyse(lines: list[str]) -> dict:
    res = {
        "version": None, "ok": None, "failed": None, "skipped": None,
        "skipped_names": [], "failed_lines": [],
        "resolved": {}, "fired": {},
        "connectivity": False, "handshake": False, "poller": False,
        "alarms": {},
    }
    for line in lines:
        m = SESSION_START.search(line)
        if m:
            res["version"] = m.group(1)
        m = PATCH_TOTALS.search(line)
        if m:
            res["ok"], res["failed"], res["skipped"] = (int(m.group(1)), int(m.group(2)),
                                                        int(m.group(3)))
        m = PATCH_SKIP.search(line)
        if m:
            res["skipped_names"].append(m.group(1).split(".")[-1])
        m = PATCH_FAILED.search(line)
        if m:
            res["failed_lines"].append(m.group(1).strip()[:160])
        m = TARGET_RESOLVED.search(line)
        if m:
            res["resolved"][m.group(1)] = m.group(2)
        m = FIRED.search(line)
        if m:
            res["fired"][m.group(1)] = res["fired"].get(m.group(1), 0) + 1
        if CONNECT_OK in line:
            res["connectivity"] = True
        if HANDSHAKE_OK in line:
            res["handshake"] = True
        if POLLER_OK in line:
            res["poller"] = True
        for marker, human in ALARM_MARKERS:
            if marker in line:
                res["alarms"][human] = res["alarms"].get(human, 0) + 1
    return res


def load_baseline() -> dict | None:
    if not BASELINE.is_file():
        return None
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except Exception:
        return None


def report(res: dict, base: dict | None, label: str) -> int:
    problems: list[str] = []
    print("=" * 70)
    print(f"Запуск мода: {label} · версия мода {res['version'] or 'не определена'}")
    print("=" * 70)

    if res["ok"] is None:
        print("  ❌ строки итога патчей нет — мод не дошёл до установки патчей")
        problems.append("нет итога патчей")
    else:
        print(f"  Патчи: применено {res['ok']}, упало {res['failed']}, "
              f"пропущено намеренно {res['skipped']}")
        if res["skipped_names"]:
            print(f"    пропущены: {', '.join(res['skipped_names'])}")
        for f in res["failed_lines"]:
            print(f"    ❌ упал: {f}")
        if res["failed"]:
            problems.append("патч не встал")

        if base and base.get("ok") is not None:
            if res["ok"] < base["ok"]:
                print(f"    ❌ ПАТЧЕЙ МЕНЬШЕ НОРМЫ: было {base['ok']}, стало {res['ok']} "
                      f"— {base['ok'] - res['ok']} не нашли цель")
                problems.append("патчей меньше нормы")
            elif res["ok"] > base["ok"]:
                print(f"    ℹ️ патчей больше нормы ({base['ok']} → {res['ok']}): "
                      "добавили новый — обнови норму через --set-baseline")
            else:
                print(f"    ✅ совпадает с нормой ({base['ok']})")
        else:
            print("    ⚠️ нормы нет — запусти с --set-baseline на заведомо здоровом логе")

    print(f"  Связь с бэкендом: {'✅' if res['connectivity'] else '❌ НЕ ДОСТУЧАЛСЯ'}")
    print(f"  Рукопожатие Module API: {'✅' if res['handshake'] else '❌ НЕТ'}")
    print(f"  Опрос заданий запущен: {'✅' if res['poller'] else '❌ НЕТ'}")
    for key, ok in (("connectivity", res["connectivity"]), ("handshake", res["handshake"]),
                    ("poller", res["poller"])):
        if not ok:
            problems.append(key)

    if res["resolved"]:
        print("  Патчи, назвавшие свою цель:")
        for name, target in res["resolved"].items():
            fired = res["fired"].get(name, 0)
            mark = f"сработал {fired}×" if fired else "НИ РАЗУ не сработал за сессию"
            print(f"    · {name}: {target.split('.')[-1]} — {mark}")

    if res["alarms"]:
        print("  Тревожные строки:")
        for human, n in res["alarms"].items():
            fatal = human in FATAL_ALARMS
            print(f"    {'❌' if fatal else '⚠️'} {human}: {n}")
            if fatal:
                problems.append(human)

    print()
    if problems:
        # Один и тот же дефект приходит и счётчиком, и тревожной строкой —
        # в вердикте он должен прозвучать один раз, иначе строка нечитаема.
        seen, unique = set(), []
        for pr in problems:
            if pr not in seen:
                seen.add(pr)
                unique.append(pr)
        print(f"ВЕРДИКТ: РЕГРЕСС — {'; '.join(unique)}")
        return 1
    print("ВЕРДИКТ: норма")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--all-sessions", action="store_true")
    ap.add_argument("--set-baseline", action="store_true")
    args = ap.parse_args()

    path = Path(args.file) if args.file else newest_log()
    if not path or not path.is_file():
        print(f"Лог мода не найден (искал в {LOG_DIR})", file=sys.stderr)
        return 2

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    sessions = split_sessions(lines)
    print(f"Файл: {path.name} · запусков в нём: {len(sessions)}")
    print()

    chosen = sessions if args.all_sessions else sessions[-1:]
    base = load_baseline()
    worst = 0
    for i, s in enumerate(chosen, 1):
        label = f"{i} из {len(chosen)}" if len(chosen) > 1 else "последний"
        worst = max(worst, report(analyse(s), base, label))
        print()

    if args.set_baseline:
        res = analyse(sessions[-1])
        if res["ok"] is None:
            print("Норму не записал: в этом запуске нет итога патчей.", file=sys.stderr)
            return 2
        BASELINE.write_text(json.dumps({
            "ok": res["ok"], "skipped": res["skipped"],
            "skipped_names": res["skipped_names"],
            "mod_version": res["version"], "source_log": path.name,
            "note": ("Норма записана с заведомо здорового запуска. Меняется ОСОЗНАННО: "
                     "после добавления патча или переезда на новую версию игры, "
                     "и только когда проверено, что механики реально работают."),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Норма записана в {BASELINE.name}: ok={res['ok']}, skipped={res['skipped']}")
        return 0

    return worst


if __name__ == "__main__":
    sys.exit(main())

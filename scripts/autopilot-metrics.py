"""Метрики автопилота Bannerlord по его логу — после эфира (23.09.2026).

Отвечает на вопрос «играет ли он агрессивно и с толком»: сколько боёв в час
работы, сколько из них похоже на победу, охоты, осады, плен героя, простои и
самовыключения. База до «Охоты»: 21.09 — 7,7 боя/ч, 22.09 — 10,8 боя/ч.

Запуск:
    python scripts/autopilot-metrics.py                # последний лог
    python scripts/autopilot-metrics.py 20260922 20260923
    python scripts/autopilot-metrics.py путь/к/autopilot_20260922.txt

Лог: Документы/Mount and Blade II Bannerlord/Logs/autopilot_ГГГГММДД.txt.
Все числа — счёт строк лога; «победы» — оценка по экрану пленных, который
бывает и после убежищ; надёжный признак поражения — плен героя.
"""
import os
import re
import sys
from pathlib import Path

LOG_DIR = Path(os.environ.get("USERPROFILE", "~")).expanduser() / "Documents" / "Mount and Blade II Bannerlord" / "Logs"
TIME = re.compile(r"^(\d\d):(\d\d):(\d\d)")

# (ключ, подпись, признак строки)
COUNTERS = [
    ("battles", "боёв (миссий)", "БОЙ: результат определён игрой"),
    # Экран пленных открывается победителю — но и после убежищ, которые в
    # «боях» выше не считаются: 21.09 вышло 60 экранов на 55 боёв. Это не счёт
    # побед, а верхняя оценка; поражение надёжно видно только по плену героя.
    ("wins", "экранов пленных после боя (≈ победы, вкл. убежища)", "ПЛЕННЫЕ: экран закрыт штатно"),
    ("sieges", "начато осад", "ОПЕРАЦИЯ: town_besiege"),
    ("taken", "взято крепостей", "ОПЕРАЦИЯ: menu_settlement_taken_continue"),
    ("siege_first", "осада вместо набора", "осада важнее набора"),
    ("defense", "выездов на оборону", "ОБОРОНА: «"),
    ("flee", "отходов от армии в разы сильнее", "ОТХОД: «"),
    ("shelter", "отсидок в укрытии", "УКРЫТИЕ: сидим"),
    ("politics", "предложений королевству (война/мир/союз)", "ПОЛИТИКА: предлагаем"),
    ("retreat", "отступлений из боя (раненый герой / враг в разы сильнее)", "отход штатной кнопкой"),
    ("sendtroops", "авторасчётов «Послать воинов»", "штатное «Послать воинов»"),
    ("siegelift", "снятых осад перед армией", "снимаем осаду до удара"),
    ("captured", "герой в плену (сдача/захват)", ("ОПЕРАЦИЯ: surrender", "ОПЕРАЦИЯ: taken_prisoner_continue")),
    ("idle", "простоев (время стоит)", "ПРОСТОЙ:"),
]


def resolve(args):
    if not args:
        logs = sorted(LOG_DIR.glob("autopilot_*.txt"))
        return logs[-1:] if logs else []
    out = []
    for a in args:
        p = Path(a)
        out.append(p if p.exists() else LOG_DIR / f"autopilot_{a}.txt")
    return out


def seconds(line):
    m = TIME.match(line)
    return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) if m else None


def analyse(path):
    counts = {key: 0 for key, _, _ in COUNTERS}
    hunts = {"отряд лорда": 0, "бандиты": 0}
    self_off = {}
    active, started, last = 0, None, None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        t = seconds(line)
        if t is not None:
            if last is not None and t < last:
                t += 86400  # сеанс перевалил за полночь
            last = t
        for key, _, mark in COUNTERS:
            marks = mark if isinstance(mark, tuple) else (mark,)
            if any(m in line for m in marks):
                counts[key] += 1
        if "ОХОТА: атакуем" in line:
            hunts["отряд лорда" if "отряд лорда" in line else "бандиты"] += 1
        if "ВКЛЮЧЕН, режим применение" in line and t is not None:
            started = t
        elif "итог сеанса" in line and started is not None and t is not None:
            active += max(0, t - started)
            started = None
        if "ВЫКЛЮЧЕНИЕ:" in line and "F12" not in line and "выключено игроком" not in line:
            reason = re.sub(r"«[^»]*»", "«…»", line.split("ВЫКЛЮЧЕНИЕ:", 1)[1].strip())
            reason = re.sub(r"\d+", "N", reason)[:90]
            self_off[reason] = self_off.get(reason, 0) + 1
    if started is not None and last is not None:
        active += max(0, last - started)  # лог оборвался на включённом автопилоте
    return counts, hunts, self_off, active / 3600


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    paths = resolve(sys.argv[1:])
    missing = [p for p in paths if not p.exists()]
    if not paths or missing:
        print("лог не найден:", ", ".join(str(p) for p in missing) or LOG_DIR)
        return 2
    for path in paths:
        counts, hunts, self_off, hours = analyse(path)
        print(f"== {path.name}: автопилот в режиме F11 {hours:.1f} ч")
        per_hour = counts["battles"] / hours if hours > 0 else 0.0
        print(f"   боёв в час работы: {per_hour:.1f}")
        for key, label, _ in COUNTERS:
            print(f"   {label}: {counts[key]}")
        print(f"   охот всего: {hunts['отряд лорда'] + hunts['бандиты']} "
              f"(лорды {hunts['отряд лорда']}, бандиты {hunts['бандиты']})")
        if self_off:
            print("   самовыключения (не F12):")
            for reason, n in sorted(self_off.items(), key=lambda kv: -kv[1]):
                print(f"     {n} x {reason}")
        else:
            print("   самовыключений (не F12): 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())

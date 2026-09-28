"""
test_single_write_path.py — одну запись делает одно место.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_single_write_path.py

## Зачем

Класс дефекта, всплывший дважды:

• покупка предмета жила в двух местах, и правку внесли только в одно;
• время просмотра писалось И серверным циклом, И heartbeat'ом панели —
  у зрителя, сидевшего одновременно в чате и в панели, опыт шёл вдвое. У
  владельца канала накопилось 19 096 «минут просмотра» при 16 352 минутах
  всех эфиров за историю: больше, чем физически шло вещание.

Общее у обоих случаев одно: два куска кода делают одну и ту же запись. Пока
они одинаковые, всё выглядит рабочим; расходятся они молча, при первой же
правке в одном из них.

Тест держит инвариант: в боевом коде ровно одна точка вставки в таблицы
времени и дохода. Появился второй INSERT — красный, и это повод либо свести
их, либо осознанно вписать сюда исключение.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

BACKEND = Path(__file__).resolve().parents[1]

# Таблица → сколько мест вставки допустимо и почему.
EXPECTED = {
    "activity_stats": (1, "только credit_viewer_minute — вместе с деньгами и часами"),
    "points_income": (1, "только record_income_tx — обе точки входа зовут её"),
    "viewer_reward_clock": (1, "часы начисления ведёт credit_viewer_minute"),
    "cases": (1, "выдача кейса всегда через grant_case"),
}

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else " — " + detail))
    if not ok:
        fails.append(name)


def main() -> int:
    files = [p for p in BACKEND.rglob("*.py")
             if "tests" not in p.parts and "__pycache__" not in p.parts
             and "migrations" not in p.parts]

    for table, (limit, why) in EXPECTED.items():
        pattern = re.compile(r"INSERT\s+INTO\s+" + table + r"\b", re.I)
        places = []
        for p in files:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").split("\n"), 1):
                if pattern.search(line):
                    places.append(f"{p.relative_to(BACKEND)}:{i}")
        check(f"{table}: одна точка записи ({why})",
              len(places) <= limit,
              f"мест {len(places)}: " + ", ".join(places))

    print()
    if fails:
        print(f"ПРОВАЛЕНО: {len(fails)} — " + "; ".join(fails))
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())

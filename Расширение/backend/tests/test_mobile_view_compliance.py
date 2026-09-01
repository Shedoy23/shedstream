"""
test_mobile_view_compliance.py — мобильный вид под правило 3.5, без перебора.

Standalone (без pytest). Запуск из backend/:
    python tests/test_mobile_view_compliance.py

ЗАЧЕМ. 24.08 Twitch отклонил 0.0.2: «The Mobile view of your Extension contains
content that exceeds Twitch's minimum App Store age rating (13+). Games with
gambling orientation are not allowed for mobile». Претензия к тому, как
поверхность ЧИТАЕТСЯ, а не к деньгам: ставок у нас нет.

Что вырезано из мобильной оболочки и почему именно это:

  * **кубики** — исход броска, и сезонный рейтинг в них набирается удачей;
  * **кейсы** — сундук с тирами и разбросом ценности, читается как лутбокс
    быстрее всего остального.

Что ОСТАВЛЕНО и почему это не перебор:

  * **крестики** — с 01.09 в `routes/tictactoe.py` нет ни одного вызова
    случайности (автоход по таймауту детерминирован);
  * **дуэли (RPS)** — `routes/rps.py` объявляет генератор и нигде его не
    использует: одновременный выбор двух людей, нулевая системная случайность.

Оба факта проверяемы ревьюером грепом, поэтому прятать эти две игры значило бы
сдать ровно то, что защищать легче всего.

Тест держит четыре границы:

1. В мобильной оболочке нет ни плиток, ни скриптов кубиков и кейсов.
2. В десктопной они ОСТАЛИСЬ — правило 3.5 про мобильный вид, и «уборка ради
   симметрии» не должна выкосить их везде.
3. В мобильной остались крестики и дуэли — защита от обратного перебора.
4. В `tictactoe.py` нет случайности вообще: утверждение «игра на навык» должно
   быть правдой в коде, а не в описании.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
FRONTEND = BACKEND.parent / "frontend"

failures: list[str] = []


def check(ok: bool, what: str, detail: str = "") -> None:
    if ok:
        print(f"  OK  {what}")
    else:
        print(f"  FAIL {what}{(' -- ' + detail) if detail else ''}")
        failures.append(what)


mobile = (FRONTEND / "mobile.html").read_text(encoding="utf-8")
desktop = (FRONTEND / "extension.html").read_text(encoding="utf-8")

print("=" * 70)
print("1. Мобильный вид не несёт механик со случайным исходом")
print("=" * 70)

for marker, name in (('data-action="dice"', "плитка кубиков"),
                     ('data-action="cases"', "плитка кейсов")):
    check(marker not in mobile, f"в мобильной оболочке нет: {name}",
          "вернулась карточка, из-за которой пришёл отказ")

for src, name in (('src="dice.js', "скрипт кубиков"),
                  ('src="cases.js', "скрипт кейсов")):
    check(src not in mobile, f"в мобильной оболочке не грузится: {name}",
          "код механики уехал бы ревьюеру вместе со сборкой")

check(not re.search(r"Common\s*—\s*70%", mobile),
      "в мобильной оболочке нет раскрытия шансов кейсов",
      "раскрытие шансов для механики, которой на экране нет, читается буквально")

print()
print("=" * 70)
print("2. Десктопная оболочка НЕ выкошена заодно")
print("=" * 70)

for marker, name in (('data-action="dice"', "кубики"),
                     ('data-action="cases"', "кейсы")):
    check(marker in desktop, f"в десктопной оболочке остались: {name}",
          "правило 3.5 про мобильный вид, десктоп трогать не просили")

check(bool(re.search(r"Common\s*—\s*70%", desktop)),
      "в десктопной оболочке раскрытие шансов кейсов на месте")

print()
print("=" * 70)
print("3. Из мобильной не вырезано лишнее")
print("=" * 70)

for marker, name in (('data-action="tictactoe"', "крестики"),
                     ('data-action="duels"', "дуэли")):
    check(marker in mobile, f"в мобильной оболочке остались: {name}",
          "это игры без системной случайности, прятать их незачем")

print()
print("=" * 70)
print("4. «Игра на навык» — правда в коде, а не в описании")
print("=" * 70)


def code_only(src: str) -> str:
    """Отбросить хвосты-комментарии: память о том, что убрали, — не нарушение."""
    return " ".join(line.split("#", 1)[0] for line in src.splitlines())


ttt = code_only((BACKEND / "routes" / "tictactoe.py").read_text(encoding="utf-8"))
check("random" not in ttt, "в tictactoe.py нет ни одного упоминания random в коде",
      "автоход по таймауту снова кидает кубик в призовой партии")

rps = code_only((BACKEND / "routes" / "rps.py").read_text(encoding="utf-8"))
check(".random(" not in rps and ".choice(" not in rps and ".randint(" not in rps,
      "в rps.py нет вызовов случайности",
      "исчез аргумент, которым мы защищаем дуэли перед ревьюером")

print()
print("=" * 70)
if failures:
    print(f"ПРОВАЛ: {len(failures)}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ВСЁ ЗЕЛЁНОЕ")
sys.exit(0)

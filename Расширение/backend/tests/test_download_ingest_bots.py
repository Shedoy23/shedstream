"""
test_download_ingest_bots.py — воронка не должна считать роботов людьми.

Standalone (без pytest). Запуск из backend/:
    python tests/test_download_ingest_bots.py

ЗАЧЕМ. 2026-09-01: из десяти последних «скачиваний» Manager девять сделали
краулеры — Amazonbot, MJ12bot, LohiSoftBot и сканеры с подставным
iPhone-User-Agent. Скрипт `scripts/ingest-download-events.py` брал из строки
журнала только время, путь и код ответа, то есть отличить робота от человека не
мог в принципе. Первая ступень воронки («сколько раз скачали») — единственный
показатель «до нас дошли», и он врал в плюс.

Что тест держит:

1. **Известный робот не попадает в воронку.** Иначе метрика растёт от
   поисковиков, а не от людей.
2. **Обычный браузер попадает.** Фильтр, который режет заодно людей, хуже
   отсутствующего: он тихо занижает единственный сигнал.
3. **Наш собственный curl с сервера не попадает** — это самопроверка деплоя, а
   не зритель.
4. **Строка без User-Agent считается.** Осознанный выбор в пользу человека:
   потерять живого важнее, чем пропустить редкого робота.

ЧЕГО ТЕСТ НЕ ОБЕЩАЕТ. Сканеры, притворяющиеся браузером, проходят и будут
проходить: по подписи их не отличить. Поэтому скрипт печатает, скольких он
отсеял, — число отсеянных и есть мера того, насколько верхняя ступень воронки
вообще заслуживает доверия.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
SCRIPT = HERE.parent.parent.parent / "scripts" / "ingest-download-events.py"

spec = importlib.util.spec_from_file_location("ingest_download_events", SCRIPT)
ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest)

failures: list[str] = []


def check(ok: bool, what: str, detail: str = "") -> None:
    if ok:
        print(f"  ✅ {what}")
    else:
        print(f"  ❌ {what}{(' — ' + detail) if detail else ''}")
        failures.append(what)


def line(agent: str) -> str:
    """Строка журнала nginx ровно того формата, что лежит на проде."""
    return ('1.2.3.4 - - [31/Aug/2026:14:09:13 +0000] '
            '"GET /releases/ShedLink.Manager-0.1.0-alpha.13-win-x64.zip HTTP/1.1" '
            '200 67858655 "-" "%s"' % agent)


CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
AMAZONBOT = ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
             "Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot) "
             "Chrome/119.0.6045.214 Safari/537.36")
MJ12 = "Mozilla/5.0 (compatible; MJ12bot/v1.4.8; http://mj12bot.com/)"
LOHISOFT = "LohiSoftBot/1.0 (+message@lohisoft.com)"

print("=" * 70)
print("Воронка скачиваний: роботы отсеиваются, люди — нет")
print("=" * 70)

check(ingest.parse_line(line(CHROME)) is not None,
      "обычный Chrome считается скачиванием",
      "фильтр режет живых — это хуже, чем не фильтровать")

for name, agent in (("Amazonbot", AMAZONBOT), ("MJ12bot", MJ12), ("LohiSoftBot", LOHISOFT)):
    check(ingest.parse_line(line(agent)) is None,
          f"{name} не попадает в воронку",
          "робот засчитан как человек")

check(ingest.parse_line(line("curl/8.5.0")) is None,
      "наша самопроверка деплоя (curl) не попадает в воронку")

no_agent = ('1.2.3.4 - - [31/Aug/2026:14:09:13 +0000] '
            '"GET /releases/ShedLink.Manager-0.1.0-alpha.13-win-x64.zip HTTP/1.1" 200 67858655')
check(ingest.parse_line(no_agent) is not None,
      "строка без User-Agent засчитывается (выбор в пользу человека)")

check(ingest.parse_line(line(CHROME).replace(" 200 ", " 404 ")) is None,
      "404 не считается скачиванием (старое поведение цело)")

print()
print("=" * 70)
if failures:
    print(f"ПРОВАЛ: {len(failures)} проверок")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ВСЁ ЗЕЛЁНОЕ")
sys.exit(0)

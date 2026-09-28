# -*- coding: utf-8 -*-
"""check-shedcolony-jar.py — jar умеет всё, что бэкенд продаёт зрителю.

    python scripts/check-shedcolony-jar.py [путь-к-jar]

Без аргумента проверяет тот файл, который забирает `pack-shedcolony-release.ps1`.
Выход: 0 — покрыто всё, 1 — есть платные действия, которых мод не знает,
2 — проверить не удалось (нет файла, битый zip).

ЗАЧЕМ. 28.08 на эфире `colonist.give_tools` за 2500 крустиков вернулся с
`unknown_action`. Разбор показал: в релизном ZIP от 19.08 лежит jar, собранный
ДО того, как 12 действий были дописаны, — их знает исходник и знает бэкенд, но
не знает мод. Двенадцать кнопок на 299 300 крустиков обещали «сделаем через
пару секунд» и не делали ничего (деньги возвращались, обещание — нет).

Механизм: `pack-shedcolony-release.ps1` берёт jar из репозитория по
фиксированному пути, куда его когда-то положили руками. Ничто не связывает
этот файл со сборкой, а номер версии у старого и нового одинаковый — по нему
подмену не увидеть. Проверка закрывает ровно это: перед упаковкой сверяем
список платных действий бэкенда с байтами jar.

Строки действий лежат в constant pool .class-файлов — отсюда и поиск подстрок,
без парсинга байткода. Ложноположительных не бывает: имя действия попадает в
jar только если оно упомянуто в коде.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIP_DIR = ROOT / "Расширение" / "frontend" / "downloads" / "minecraft"
PRICES_SRC = ROOT / "Расширение" / "backend" / "routes" / "shedcolony.py"


def priced_actions() -> dict:
    src = PRICES_SRC.read_text(encoding="utf-8")
    return {a: int(p) for a, p in re.findall(
        r'"((?:colonist|colony)\.[a-z_]+)"\s*:\s*(\d+)', src)}


def jar_actions(path: Path) -> bytes:
    with zipfile.ZipFile(path) as z:
        return b"".join(z.read(n) for n in z.namelist() if n.endswith(".class"))


def main() -> int:
    if len(sys.argv) > 1:
        jar = Path(sys.argv[1])
    else:
        # Версию не зашиваем: берём самый свежий jar из папки отгрузки.
        found = sorted(SHIP_DIR.glob("shedcolony-*.jar"))
        if not found:
            print(f"[shedcolony-jar] НЕ ПРОВЕРЕНО: в {SHIP_DIR} нет ни одного jar")
            return 2
        jar = found[-1]
    if not jar.is_file():
        print(f"[shedcolony-jar] НЕ ПРОВЕРЕНО: файла нет — {jar}")
        return 2
    prices = priced_actions()
    if not prices:
        print(f"[shedcolony-jar] НЕ ПРОВЕРЕНО: не нашёл цен в {PRICES_SRC.name} — "
              "формат словаря цен изменился, проверку надо чинить, а не игнорировать")
        return 2
    try:
        blob = jar_actions(jar)
    except (zipfile.BadZipFile, OSError) as exc:
        print(f"[shedcolony-jar] НЕ ПРОВЕРЕНО: {jar.name} не читается — {exc}")
        return 2

    missing = sorted(((a, p) for a, p in prices.items() if a.encode() not in blob),
                     key=lambda x: -x[1])
    if not missing:
        print(f"[shedcolony-jar] OK: {jar.name} умеет все {len(prices)} платных действий")
        return 0

    total = sum(p for _, p in missing)
    print(f"[shedcolony-jar] ОШИБКА: {jar.name} не умеет {len(missing)} из "
          f"{len(prices)} платных действий (кнопок на {total} крустиков):")
    for a, p in missing:
        print(f"    {a:34} {p:>6} крустиков")
    print("  Это мёртвые кнопки: зритель платит, получает «заявка принята» и ничего.")
    print("  Скорее всего jar собран раньше, чем дописаны действия — пересобери мод")
    print("  и положи свежий jar на место, а не упаковывай этот.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

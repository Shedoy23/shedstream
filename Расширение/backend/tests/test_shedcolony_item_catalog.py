"""
test_shedcolony_item_catalog.py — список товаров ShedColony живёт в ОДНОМ месте
и доезжает до зрителя с сервера.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_shedcolony_item_catalog.py

## Что за дыра

До 2026-09-06 каждый список предметов существовал дважды: сет id в
`routes/shedcolony.py` (по нему валидируется покупка) и массив [id, подпись] в
`frontend/viewer-shedcolony.js` (его видит зритель). Во фронте прямо стоял
комментарий «MUST stay a subset» — то есть совпадение держалось на внимании
человека. Две копии одного списка расходятся молча при первой правке одной из
них: зритель выбирает товар, которого бэкенд уже не принимает, и получает отказ
на ровном месте — либо наоборот, снятый с продажи товар остаётся в панели.

Хуже: фронт замерзает на CDN Twitch до следующего ревью (недели), а бэкенд
деплоится за минуты. Пока список зашит во фронте, убрать испортившийся товар
нельзя без новой подачи расширения. Ровно этим 05.09 отличилась сабля Wolfein в
RimWorld: 5 покупок по 5520💎, 0 успехов, снять нечем.

## Чего требуем

1. `/api/shedcolony/config` отдаёт каталоги всех трёх пикеров парами
   [id, подпись] — иначе панели нечего рисовать.
2. Множество id каждого каталога РАВНО множеству, по которому бэкенд
   валидирует покупку. Не «подмножество», а равенство: показываем ровно то,
   что примем.
3. Фронт присваивает свои списки из `item_catalog` — иначе сервер может слать
   что угодно, зритель этого не увидит.

Красный до фикса: в конфиге нет `item_catalog` (пункт 1), а фронт держит
собственную правду (пункт 3).
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
FRONTEND = BACKEND.parent / "frontend"
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else " — " + detail))
    if not ok:
        fails.append(name)


async def main() -> int:
    from routes.shedcolony import (
        _GIVE_ITEM_WHITELIST,
        _MIN_STOCK_WHITELIST,
        _SUPPLY_WHITELIST,
        shedcolony_config,
    )

    cfg = await shedcolony_config()
    catalog = cfg.get("item_catalog") or {}

    expected = {
        "give_item": ("что выдать колонисту", _GIVE_ITEM_WHITELIST),
        "supply": ("что отправить на склад", _SUPPLY_WHITELIST),
        "min_stock": ("что закрепить в запасе", _MIN_STOCK_WHITELIST),
    }

    for key, (human, whitelist) in expected.items():
        rows = catalog.get(key)
        ok_shape = (
            isinstance(rows, list)
            and bool(rows)
            and all(isinstance(r, (list, tuple)) and len(r) == 2
                    and isinstance(r[0], str) and r[0]
                    and isinstance(r[1], str) and r[1]
                    for r in rows)
        )
        check(f"каталог «{human}» приходит парами [id, подпись]", ok_shape, repr(rows)[:120])
        if not ok_shape:
            continue
        ids = {r[0] for r in rows}
        check(f"каталог «{human}» совпадает с тем, что бэкенд примет",
              ids == set(whitelist),
              f"только в каталоге: {sorted(ids - set(whitelist))}; "
              f"только в разрешённых: {sorted(set(whitelist) - ids)}")
        check(f"в каталоге «{human}» нет повторов", len(ids) == len(rows),
              f"{len(rows)} строк, {len(ids)} уникальных")

    # Фронт обязан брать список с сервера, иначе пункты выше бесполезны.
    src = (FRONTEND / "viewer-shedcolony.js").read_text(encoding="utf-8")
    check("фронт читает item_catalog из конфига", "item_catalog" in src)
    for var, field in (("SC_GIVE_ITEMS", "give_item"),
                       ("SC_SUPPLY_ITEMS", "supply"),
                       ("SC_MIN_STOCK_ITEMS", "min_stock")):
        assigned = re.search(rf"{var}\s*=\s*(?!\[)", src) is not None
        check(f"фронт перетирает {var} серверным списком", assigned,
              "нашлось только литеральное объявление — серверный каталог не доедет")
        check(f"фронт запрашивает поле {field}", f"cat.{field}" in src)

    print()
    if fails:
        print(f"ПРОВАЛЕНО: {len(fails)} — " + "; ".join(fails))
        return 1
    print("ВСЁ ЗЕЛЁНОЕ: список товаров ShedColony один, и он приезжает с сервера.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

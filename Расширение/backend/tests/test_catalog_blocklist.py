"""
test_catalog_blocklist.py — товар из чёрного списка не доходит до зрителя.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_catalog_blocklist.py

## Зачем

Каталог RimWorld строится модом из DefDatabase — принцип: изменение содержимого
игры расширение переживает без правок. Обратная сторона: в продажу попадает и
то, что на этой сборке выдать НЕЛЬЗЯ. Сабля `W_Weapon_Melee_Sheathe` из мода
Wolfein продавалась за 5520💎 и не выдалась ни разу — 5 покупок, 0 успехов,
падение внутри чужого MVCF.

Снятие такого товара через список в моде стоит релиза DLL и перезапуска игры у
стримера. Серверный фильтр гасит его деплоем за минуты.

## Чего требуем

1. Позиция из чёрного списка не попадает в `shop_catalog` при приёме каталога.
2. Остальные позиции сохраняются — фильтр не задевает соседей.
3. Покупка заблокированного отклоняется ДО списания: `buy-item` ищет строку в
   каталоге, а её нет.
4. Префиксный запрет работает так же (на случай сломанного семейства).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

for _k, _v in (
    ("TWITCH_OAUTH_TOKEN", "oauth:test"), ("TWITCH_CLIENT_ID", "test_client"),
    ("TWITCH_CLIENT_SECRET", "test_secret"), ("TWITCH_BOT_ID", "test_bot"),
    ("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab"),
    ("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890"),
    ("ADMIN_PASSWORD", "test_admin_password_for_tests_only"),
):
    os.environ.setdefault(_k, _v)

CH = 990311
fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else " — " + detail))
    if not ok:
        fails.append(name)


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


async def main() -> int:
    import config
    from database import Database
    from dependencies import set_db
    import rimworld

    db = Database("viewers.db")
    await db.init_pool()
    set_db(db)

    # Свой предмет-семейство для проверки префикса — чтобы не зависеть от
    # содержимого боевого списка.
    config.RIMWORLD_CATALOG_BLOCKLIST_PREFIXES = ("BrokenFamily_",)

    payload = [
        {"category": "weapon", "def_name": "W_Weapon_Melee_Sheathe", "label": "Сабля", "price": 5520},
        {"category": "weapon", "def_name": "Gun_Revolver", "label": "Револьвер", "price": 900},
        {"category": "apparel", "def_name": "BrokenFamily_Hat", "label": "Шляпа", "price": 300},
        {"category": "apparel", "def_name": "Apparel_Parka", "label": "Парка", "price": 400},
    ]

    async def cleanup():
        # Таблицу создаёт сам обработчик при первом приёме каталога, поэтому до
        # первого вызова её может не быть — это не ошибка теста.
        try:
            async with db._connect() as conn:
                await conn.execute("DELETE FROM shop_catalog WHERE channel_id=?", (CH,))
                await conn.commit()
        except Exception:
            pass

    try:
        await cleanup()
        await rimworld.receive_shop_catalog(_FakeRequest(payload), _auth=CH)

        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT def_name FROM shop_catalog WHERE channel_id=?", (CH,))
            stored = {r[0] for r in await cur.fetchall()}

        check("сабля не попала в каталог", "W_Weapon_Melee_Sheathe" not in stored, str(stored))
        check("запрет по префиксу сработал", "BrokenFamily_Hat" not in stored, str(stored))
        check("соседние позиции сохранены",
              {"Gun_Revolver", "Apparel_Parka"} <= stored, str(stored))

        # Покупка заблокированного: строки в каталоге нет → отказ до списания.
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM shop_catalog WHERE channel_id=? AND def_name=?",
                (CH, "W_Weapon_Melee_Sheathe"))
            found = (await cur.fetchone())[0]
        check("покупка не найдёт заблокированный предмет", found == 0, f"строк {found}")
    finally:
        await cleanup()
        try:
            await db._pool.close()
        except Exception:
            pass

    print()
    if fails:
        print(f"ПРОВАЛЕНО: {len(fails)} — " + "; ".join(fails))
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

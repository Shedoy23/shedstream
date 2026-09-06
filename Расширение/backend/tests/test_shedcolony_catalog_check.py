"""
test_shedcolony_catalog_check.py — товар, которого нет в сборке стримера, не
доезжает до зрителя.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_shedcolony_catalog_check.py

## Что за дыра

Каталог товаров живёт на бэкенде, а играют в модпаке из сотен модов — бэкенд не
знает, что в нём есть. Зритель платит за выдачу предмета, которого в сборке
может не оказаться: деньги списаны, эффекта нет. Тот же класс 05.09 дала сабля
Wolfein в RimWorld — 5 покупок по 5520💎 и 0 успехов.

Теперь мод сверяет каталог с реестром предметов СВОЕЙ сборки и шлёт
`colony.catalog` со списком отсутствующего; `/api/shedcolony/config` его
вычитает. Своего списка мод не держит — каталог остаётся один, на бэкенде.

## Чего требуем

1. Пришло «этих двух у меня нет» — они исчезают из каталога, соседние остаются.
2. Мод молчит (не запускался, старая версия) — торгуем полным каталогом.
   Показать лишнее дешевле, чем схлопнуть магазин на пустом месте.
3. Ответ, где отсутствует ВЕСЬ каталог, отбрасывается: так не бывает даже на
   голой ванили, и гасить по нему весь магазин нельзя.
4. Мусор вместо списка не стирает прошлый честный ответ.

Красный до фикса: события `colony.catalog` нет в манифесте (бэкенд молча его
отбрасывает), таблицы нет, конфиг ничего не вычитает.
"""
from __future__ import annotations

import asyncio
import json
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

CH = 990312
fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else " — " + detail))
    if not ok:
        fails.append(name)


async def main() -> int:
    from database import Database
    from dependencies import set_db
    from modules._base import ModuleEnvelope
    from modules._loader import load_manifest
    from modules.shedcolony._adapter import ShedColonyAdapter
    from routes.shedcolony import _GIVE_ITEM_CATALOG, shedcolony_config

    db = Database("viewers.db")
    await db.init_pool()
    set_db(db)

    # Событие обязано быть объявлено в манифесте, иначе бэкенд его отбросит
    # молча (event_not_in_manifest) — мод пишет в лог, база не меняется.
    manifest = (BACKEND / "modules" / "shedcolony" / "manifest.yaml").read_text(encoding="utf-8")
    check("colony.catalog объявлено в манифесте", "colony.catalog" in manifest)

    adapter = ShedColonyAdapter(
        load_manifest(BACKEND / "modules" / "shedcolony" / "manifest.yaml"))
    all_ids = [item for item, _ in _GIVE_ITEM_CATALOG]
    gone = all_ids[:2]

    def env(data):
        return ModuleEnvelope(id="t", kind="event", type="colony.catalog", ts=0, data=data)

    async def cleanup():
        try:
            async with db._connect() as conn:
                await conn.execute(
                    "DELETE FROM shedcolony_catalog_check WHERE channel_id=?", (CH,))
                await conn.commit()
        except Exception:
            pass                       # таблицы может не быть до первой миграции — не ошибка

    async def catalog_ids():
        cfg = await shedcolony_config(channel_id=CH)
        return {row[0] for row in cfg["item_catalog"]["give_item"]}

    try:
        await cleanup()

        # 2. Мод молчит → полный каталог.
        check("без ответа мода торгуем полным каталогом",
              await catalog_ids() == set(all_ids))

        # 1. Честный ответ → эти двое исчезают, остальные на месте.
        await adapter.handle_event(CH, env({"missing": gone, "checked": len(all_ids)}))
        after = await catalog_ids()
        check("отсутствующие в сборке убраны из каталога", not (set(gone) & after), str(sorted(after)))
        check("соседние товары остались", set(all_ids[2:]) <= after,
              f"пропало лишнее: {sorted(set(all_ids[2:]) - after)}")

        # 4. Мусор не стирает прошлый честный ответ.
        await adapter.handle_event(CH, env({"missing": "не список", "checked": 5}))
        check("мусорный ответ не отменяет прошлый", await catalog_ids() == after)

        # 3. «У меня нет вообще ничего» — отбрасываем.
        await cleanup()
        await adapter.handle_event(CH, env({"missing": all_ids, "checked": len(all_ids)}))
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT data FROM shedcolony_catalog_check WHERE channel_id=?", (CH,))
            row = await cur.fetchone()
        check("ответ «нет ничего» не сохранён", row is None,
              f"сохранилось: {row[0] if row else ''}")
        check("каталог после такого ответа полный", await catalog_ids() == set(all_ids))

        # И защита второго уровня: даже если такая строка появится в базе руками,
        # конфиг не отдаёт пустой пикер.
        async with db._connect() as conn:
            await conn.execute(
                "INSERT INTO shedcolony_catalog_check (channel_id, data) VALUES (?, ?) "
                "ON CONFLICT(channel_id) DO UPDATE SET data = excluded.data",
                (CH, json.dumps({"missing": all_ids, "checked": len(all_ids)})))
            await conn.commit()
        check("пустой пикер зрителю не показываем", await catalog_ids() == set(all_ids))
    finally:
        await cleanup()
        try:
            await db._pool.close()      # иначе процесс висит после «зелёного» вывода
        except Exception:
            pass

    print()
    if fails:
        print(f"ПРОВАЛЕНО: {len(fails)} — " + "; ".join(fails))
        return 1
    print("ВСЁ ЗЕЛЁНОЕ: сборка стримера решает, что зритель видит в магазине.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

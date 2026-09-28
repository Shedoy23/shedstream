"""
test_shop_tooltip_persists.py — подсказка каталога живёт в базе, а не в файле.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_shop_tooltip_persists.py

ЧТО ДОКАЗЫВАЕТ (найдено 2026-09-10 по жалобе владельца «не показывается, что
даёт имплант»).

    Мод присылает для каждой позиции готовую подсказку: часть тела плюс
    бонусы из `HediffStage` («✦ Сознание: +15%»). Именно она отвечает на
    вопрос «что я покупаю»: описание рядом бесполезно, у рецептов вживления
    оно шаблонное («Вживить мозгорез.»).

    Все поля каталога хранились в `shop_catalog`, а подсказка — ОДНА — в
    файле `backend/tooltip_cache.json` рядом с кодом. Последствия, все три
    наблюдались:

      1. Её стирал деплой: `deploy.ps1` исключает `*.db` и `.env`, но не этот
         файл — архив вёз на прод пустую копию с машины разработчика. Лог
         прода 10.09: `Каталог обновлён: 2913 предметов, тултипов: 2913` при
         заливке и `Тултипы загружены: 0 предметов` после рестарта.
      2. У неё не было арендатора: ключ — голый `def_name`, без `channel_id`.
      3. Её не было в бэкапах: три яруса снимают базу, файл рядом с кодом — никто.

    Проверяется ПОВЕДЕНИЕМ настоящих обработчиков приёма и выдачи каталога, а
    не наличием колонки: колонка в схеме ничего не говорит о том, доезжает ли
    значение до зрителя.

ЧТО ЗДЕСЬ ПОДМЕНЕНО. Только распознавание канала у читающей ручки
(`_require_viewer_channel`) — она требует подписанный Twitch JWT, а предмет
теста не авторизация. Авторизацию держат `test_multi_tenant_isolation.py` и
`test_rimworld_channel_isolation.py`.

ТЕСТЫ:
    [1] на СТАРОЙ базе (таблица без колонки) миграция M124 её добавляет
    [2] приём каталога кладёт подсказку в базу, а не в память процесса
    [3] подсказка переживает рестарт: её видит новое соединение
    [4] выдача каталога отдаёт подсказку зрителю
    [5] чужой канал своей подсказки не отдаёт
    [6] позиция без подсказки не ломает выдачу
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

HERE = Path(__file__).parent.absolute()
sys.path.insert(0, str(HERE.parent))

for _v, _d in (("TWITCH_OAUTH_TOKEN", "oauth:test"), ("TWITCH_CLIENT_ID", "c"),
               ("TWITCH_CLIENT_SECRET", "s"), ("TWITCH_BOT_ID", "b"),
               ("TWITCH_CHANNEL_NAME", "ch"),
               ("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab"),
               ("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890"),
               ("ADMIN_PASSWORD", "test_admin_password_for_tests_only"),
               ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(_v, _d)

CH_A = 98319857
CH_B = 5150001
TIP = "🦿 мозг\n✦ Сознание: +15%\n✦ Психочувствительность: ×1,2"

_failures: list = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}" + (f" — {detail}" if detail else "")
        _failures.append(msg)
        print(msg)


class _FakeRequest:
    """Тело запроса мода. Больше приёмнику каталога ничего не нужно."""

    def __init__(self, payload=None):
        self._payload = payload

    async def json(self):
        return self._payload


def _item(def_name, label, tooltip=None, category="implant"):
    it = {"category": category, "def_name": def_name, "label": label,
          "desc": f"Вживить {label.lower()}.", "price": 315,
          "tech_level": "Industrial"}
    if tooltip is not None:
        it["tooltip"] = tooltip
    return it


async def _legacy_table(db):
    """Таблица каталога, какой она была до M124 — БЕЗ колонки tooltip.

    Именно такая лежит на проде, поэтому миграцию проверяем на ней, а не на
    свежесозданной: на пустой базе таблицу создаёт сам обработчик, и колонка
    там есть по определению — доказательство было бы фиктивным.
    """
    async with db._connect() as conn:
        await conn.execute("DROP TABLE IF EXISTS shop_catalog")
        await conn.execute("""
            CREATE TABLE shop_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                category TEXT, def_name TEXT, label TEXT, description TEXT,
                price INTEGER, base_price INTEGER DEFAULT 0,
                tech_level TEXT, extra_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id, def_name)
            )
        """)
        await conn.execute(
            "DELETE FROM migrations_applied WHERE name='M124.shop_catalog_tooltip'")
        await conn.commit()


async def _columns(db, table):
    async with db._connect() as conn:
        cur = await conn.execute(f"PRAGMA table_info({table})")
        return [r[1] for r in await cur.fetchall()]


async def _tooltip_in_db(db, channel_id, def_name):
    """Читаем НОВЫМ соединением — так же, как это сделал бы новый процесс."""
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT tooltip FROM shop_catalog WHERE channel_id=? AND def_name=?",
            (channel_id, def_name))
        row = await cur.fetchone()
    return row[0] if row else None


async def _build_db(db_path: str):
    import main
    import dependencies
    from database import Database

    test_db = Database(db_path)
    main.db = test_db
    dependencies.set_db(test_db)
    await test_db.init_pool()
    await test_db.init_tables()
    await main.run_migrations()
    async with test_db._connect() as conn:
        for cid, login in ((CH_A, "alice_chan"), (CH_B, "bob_chan")):
            await conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
                "VALUES (?, ?, ?, 'free')", (cid, login, login))
        await conn.commit()
    return test_db


async def run():
    db_path = tempfile.mktemp(suffix="_shop_tooltip.db")
    db = await _build_db(db_path)
    try:
        import main
        import rimworld

        print("\n[1] Старая база: миграция добавляет колонку")
        await _legacy_table(db)
        check("до миграции колонки нет",
              "tooltip" not in await _columns(db, "shop_catalog"))
        await main.run_migrations()
        check("после миграции колонка есть",
              "tooltip" in await _columns(db, "shop_catalog"),
              f"колонки: {await _columns(db, 'shop_catalog')}")

        print("\n[2-3] Приём каталога: подсказка ложится в базу и переживает рестарт")
        await rimworld.receive_shop_catalog(
            _FakeRequest([_item("Mindscrew", "Мозгорез", TIP),
                          _item("Gun_Revolver", "Револьвер", None, "weapon")]),
            _auth=CH_A)
        stored = await _tooltip_in_db(db, CH_A, "Mindscrew")
        check("подсказка лежит в строке каталога", stored == TIP,
              f"в базе: {stored!r}")
        check("подсказка целая, со статами",
              bool(stored) and "Сознание" in stored, f"в базе: {stored!r}")

        print("\n[4] Выдача каталога: зритель подсказку видит")
        rimworld._require_viewer_channel = lambda request: CH_A   # см. шапку
        resp = await rimworld.get_catalog(_FakeRequest())
        by_def = {i["def_name"]: i for i in resp["items"]}
        check("мозгорез в выдаче", "Mindscrew" in by_def,
              f"позиций: {len(resp['items'])}")
        if "Mindscrew" in by_def:
            check("у мозгореза есть подсказка",
                  by_def["Mindscrew"].get("tooltip") == TIP,
                  f"пришло: {by_def['Mindscrew'].get('tooltip')!r}")

        print("\n[5] Чужой канал своей подсказки не отдаёт")
        await rimworld.receive_shop_catalog(
            _FakeRequest([_item("Mindscrew", "Мозгорез", "ПОДСКАЗКА ДРУГОГО КАНАЛА")]),
            _auth=CH_B)
        check("у канала A подсказка не подменилась",
              await _tooltip_in_db(db, CH_A, "Mindscrew") == TIP,
              f"стало: {await _tooltip_in_db(db, CH_A, 'Mindscrew')!r}")
        check("у канала B своя подсказка",
              await _tooltip_in_db(db, CH_B, "Mindscrew") == "ПОДСКАЗКА ДРУГОГО КАНАЛА")

        print("\n[6] Позиция без подсказки не ломает выдачу")
        if "Gun_Revolver" in by_def:
            check("револьвер отдан без ключа tooltip",
                  "tooltip" not in by_def["Gun_Revolver"],
                  f"пришло: {by_def['Gun_Revolver'].get('tooltip')!r}")
    finally:
        try:
            await db._pool.close()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass


def main_() -> int:
    try:
        asyncio.run(run())
    except Exception:
        traceback.print_exc()
        return 1
    print()
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print(" ", f.strip())
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main_())

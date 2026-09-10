"""
Migration M124: `shop_catalog.tooltip` — подсказка каталога переезжает в базу.

ЗАЧЕМ (найдено 2026-09-10 по жалобе владельца «не показывается, что даёт
имплант»).

Мод присылает для КАЖДОЙ позиции каталога готовую подсказку: часть тела плюс
ключевые бонусы из `HediffStage` («✦ Сознание: +15%»). Именно она отвечает на
вопрос «что я покупаю» — описание рядом бесполезно, потому что у рецептов
вживления оно шаблонное («Вживить мозгорез.»).

Все остальные поля каталога (label, description, price, tech_level, extra_json)
хранились в `shop_catalog`, а подсказка — ОДНА — жила в файле
`backend/tooltip_cache.json` рядом с кодом. Из-за этого она:

  1. **Стиралась деплоем.** `deploy.ps1` исключает из архива `*.db` и `.env`,
     но не этот файл: архив привозил на прод пустую копию с машины
     разработчика поверх боевой. 10.09 так и случилось — лог прода показывает
     `Каталог обновлён: 2913 предметов, тултипов: 2913` при заливке и
     `Тултипы загружены: 0 предметов` после следующего рестарта.
  2. **Не имела арендатора.** Ключ — только `def_name`, без `channel_id`:
     каталог второго стримера затирал бы подсказки первого. Ровно тот случай,
     ради которого в M97 сюда добавляли `channel_id`.
  3. **Не попадала в бэкапы.** Три яруса бэкапов снимают базу; файл рядом с
     кодом не снимает никто.

Колонка в `shop_catalog` решает все три сразу: база исключена из деплоя,
скоуплена по каналу и лежит в бэкапах.

ПОСЛЕ ПРИМЕНЕНИЯ подсказки появятся не сразу: значения есть только у мода, и
приезжают они с заливкой каталога — то есть при следующем запуске RimWorld.
Пустая колонка = «мод ещё не присылал», фронт в этом случае показывает одно
описание, как раньше.

Таблица создаётся лениво (эндпоинт заливки каталога), поэтому на свежей базе
её здесь может не быть — тогда миграция пропускается, а колонку даёт CREATE
TABLE.

Аддитивно. Idempotent: migrations_applied['M124.shop_catalog_tooltip'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M124.shop_catalog_tooltip"):
        return

    if await _has_table(conn, "shop_catalog"):
        if not await _has_column(conn, "shop_catalog", "tooltip"):
            # tenant-ok: колонка в уже скоупленной по channel_id таблице каталога.
            await conn.execute(
                "ALTER TABLE shop_catalog ADD COLUMN tooltip TEXT")

    await conn.commit()
    await _mark_applied(conn, "M124.shop_catalog_tooltip")
    print("M124: shop_catalog.tooltip added")


async def _has_table(conn, table: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return await cur.fetchone() is not None


async def _has_column(conn, table: str, column: str) -> bool:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return any(r[1] == column for r in rows)


async def _ensure_migrations_table(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS migrations_applied (
            name TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def _is_applied(conn, name: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,)
    )
    return await cur.fetchone() is not None


async def _mark_applied(conn, name: str) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()

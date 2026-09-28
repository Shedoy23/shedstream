"""
Migration M31: deprecate 4 misfit catalog items (Sprint 5.22, 2026-05-20).

После 5.21/5.22 редизайна creature'а из абстрактного blob'а — некоторые
emoji items плохо ложатся на тело потому что сами содержат «человеческое»
изображение (лицо/торс), и накладывание выглядит как двойной face:

  • face_mask    😷 — маска нарисована поверх жёлтого лица emoji
  • body_tie     👔 — галстук idёт от воротника + торса, blob'у не подходит
  • hat_cowboy   🤠 — ковбойская шляпа emoji включает в себя голову+лицо
  • acc_scarf    🧣 — оригинальный шарф emoji содержит шею/тело

Зрители заметили это на бета-стримах. Решение: deprecated=1.
Foreign-key safe — items остаются в БД для existing pet_inventory /
pet_equipped rows (purchase history audit-safe), но фильтруются из:
  - GET /api/pet/catalog (list_pet_catalog WHERE deprecated=0)
  - GET /api/pet/my       (inventory JOIN deprecated=0)
  - equipped рендеринг (тот же WHERE deprecated=0)

Эффект для уже-купивших: предметы исчезают из инвентаря и со creature'а.
Refund НЕ делаем (mock-mode bits = 0 реальных потерь).

Идемпотентно через migrations_applied['M31.pets_deprecate_misfits'].
"""

DEPRECATED_ITEMS = [
    'face_mask',
    'body_tie',
    'hat_cowboy',
    'acc_scarf',
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M31.pets_deprecate_misfits"):
        return

    for item_id in DEPRECATED_ITEMS:
        await conn.execute(
            "UPDATE pet_catalog SET deprecated = 1 WHERE item_id = ?",
            (item_id,)
        )

    await conn.commit()
    await _mark_applied(conn, "M31.pets_deprecate_misfits")
    print(f"✅ M31: deprecated {len(DEPRECATED_ITEMS)} misfit pet items")


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

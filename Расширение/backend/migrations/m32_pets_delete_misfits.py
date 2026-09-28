"""
Migration M32: hard-delete 4 misfit pet items (Sprint 5.22, 2026-05-20).

После M31 (deprecated=1) тестеры ещё не получили доступ к pet'ам —
поэтому safe удалить навсегда вместо soft-deprecate.

DELETE'им из всех связанных таблиц в FK-safe порядке:
  1. pet_equipped  (если бы кто-то надел)
  2. pet_inventory (если бы кто-то купил)
  3. pet_purchases (audit log)
  4. pet_catalog   (главная запись)

Также m30_pets_catalog_expand.py обновлён чтобы на fresh-install
эти items не создавались заново (CATALOG_ADDS без них).

Items:
  • face_mask    😷 — маска поверх жёлтого emoji-лица
  • body_tie     👔 — галстук с воротником/торсом
  • hat_cowboy   🤠 — ковбойская шляпа со встроенным лицом
  • acc_scarf    🧣 — оригинальный шарф (M13 baseline) с телом

Идемпотентно через migrations_applied['M32.pets_delete_misfits'].
"""

DELETED_ITEMS = [
    'face_mask',
    'body_tie',
    'hat_cowboy',
    'acc_scarf',
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M32.pets_delete_misfits"):
        return

    placeholders = ",".join("?" * len(DELETED_ITEMS))

    # FK-safe порядок: child tables → parent
    await conn.execute(
        f"DELETE FROM pet_equipped  WHERE item_id IN ({placeholders})",
        tuple(DELETED_ITEMS)
    )
    await conn.execute(
        f"DELETE FROM pet_inventory WHERE item_id IN ({placeholders})",
        tuple(DELETED_ITEMS)
    )
    await conn.execute(
        f"DELETE FROM pet_purchases WHERE item_id IN ({placeholders})",
        tuple(DELETED_ITEMS)
    )
    await conn.execute(
        f"DELETE FROM pet_catalog   WHERE item_id IN ({placeholders})",
        tuple(DELETED_ITEMS)
    )

    await conn.commit()
    await _mark_applied(conn, "M32.pets_delete_misfits")
    print(f"✅ M32: hard-deleted {len(DELETED_ITEMS)} misfit pet items "
          "(catalog + inventory + equipped + purchases)")


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

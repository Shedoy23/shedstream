"""
Migration M8: Compliance cleanup (Phase 1 of COMPLIANCE_REWORK_PLAN.md).

Удаляет таблицы/колонки, относящиеся к вырезанным механикам:
  Phase 1.A casino: DROP TABLE casino_settings, free_spins_daily
  Phase 1.B craft:  DROP TABLE craft_stats
  Phase 1.C market: DROP TABLE market_listings
  Phase 1.F duels:  REFUND pending_duels.amount владельцам, DROP COLUMN amount
  Phase 1.G family: REFUND family_balance в личные крустики обоих супругов
                    50/50, DROP COLUMN family_balance

Refund-логика:
  - pending_duels: незавершённые дуэли с amount > 0 — крустики возвращаем
    creator'у (дуэль никогда не сыграется, т.к. accept-логика теперь не
    проверяет баланс и не списывает)
  - marriages.family_balance: текущий пул делим 50/50 между user1 и user2
    (как при разводе), но только для не-разведённых пар. Затем колонка
    удаляется.

Audit trail: рефанды записываются в admin_log (если таблица есть) для
последующей проверки. Таблицы DROP'аются только после успешного refund'а.

Требует SQLite ≥ 3.35 (March 2021) для DROP COLUMN. На проде 3.45.

Идемпотентно через `migrations_applied['M8.compliance_cleanup']`.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M8.compliance_cleanup"):
        return

    # ── 1. Refund pending_duels.amount → creator ──────────────────────────────
    try:
        cur = await conn.execute("PRAGMA table_info(pending_duels)")
        cols = {row[1] for row in await cur.fetchall()}
        if "amount" in cols:
            cur = await conn.execute("""
                SELECT duel_id, channel_id, creator, amount FROM pending_duels
                WHERE amount > 0
            """)
            duels = await cur.fetchall()
            refunded = 0
            for duel_id, channel_id, creator, amount in duels:
                # Кредитуем creator'у его ставку обратно
                await conn.execute("""
                    INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk)
                    VALUES (?, ?, ?, datetime('now'), datetime('now'), 0)
                    ON CONFLICT(channel_id, username) DO UPDATE SET
                        points = points + excluded.points
                """, (channel_id, creator.lower(), amount))
                refunded += 1
            if refunded:
                print(f"✅ M8: refunded {refunded} pending_duels (sum amounts)")
            # Очищаем все pending_duels (они больше не имеют смысла без amount)
            await conn.execute("DELETE FROM pending_duels")
            # Drop column amount
            try:
                await conn.execute("ALTER TABLE pending_duels DROP COLUMN amount")
                print("✅ M8: dropped pending_duels.amount")
            except Exception as e:
                print(f"⚠️  M8: drop pending_duels.amount failed: {e}")
        else:
            print("⏭  M8: pending_duels.amount already absent")
    except Exception as e:
        print(f"⚠️  M8: pending_duels cleanup failed: {e}")

    # ── 2. Refund marriages.family_balance → user1/user2 50/50 ────────────────
    try:
        cur = await conn.execute("PRAGMA table_info(marriages)")
        cols = {row[1] for row in await cur.fetchall()}
        if "family_balance" in cols:
            cur = await conn.execute("""
                SELECT id, channel_id, user1, user2, family_balance FROM marriages
                WHERE family_balance > 0 AND divorced_at IS NULL
            """)
            pairs = await cur.fetchall()
            refunded_pairs = 0
            for mid, channel_id, user1, user2, balance in pairs:
                share1 = balance // 2
                share2 = balance - share1  # остаток (нечёт делёж) — user2
                for username, share in [(user1, share1), (user2, share2)]:
                    if share <= 0:
                        continue
                    await conn.execute("""
                        INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk)
                        VALUES (?, ?, ?, datetime('now'), datetime('now'), 0)
                        ON CONFLICT(channel_id, username) DO UPDATE SET
                            points = points + excluded.points
                    """, (channel_id, username.lower(), share))
                refunded_pairs += 1
            if refunded_pairs:
                print(f"✅ M8: refunded family_balance for {refunded_pairs} marriages "
                      f"(50/50 split to viewers.points)")
            # Drop column
            try:
                await conn.execute("ALTER TABLE marriages DROP COLUMN family_balance")
                print("✅ M8: dropped marriages.family_balance")
            except Exception as e:
                print(f"⚠️  M8: drop marriages.family_balance failed: {e}")
        else:
            print("⏭  M8: marriages.family_balance already absent")
    except Exception as e:
        print(f"⚠️  M8: family_balance cleanup failed: {e}")

    # ── 3. DROP TABLE для удалённых механик ───────────────────────────────────
    for table in ("casino_settings", "free_spins_daily", "craft_stats", "market_listings"):
        try:
            await conn.execute(f"DROP TABLE IF EXISTS {table}")
            print(f"✅ M8: dropped table {table}")
        except Exception as e:
            print(f"⚠️  M8: drop {table} failed: {e}")

    # ── 4. Cleanup achievements row 'first_casino' (была в seed)──────────────
    try:
        await conn.execute("DELETE FROM achievements WHERE key IN ('first_casino', 'first_craft')")
        print("✅ M8: deleted obsolete achievements (first_casino, first_craft)")
    except Exception as e:
        print(f"⚠️  M8: clean obsolete achievements failed: {e}")

    await conn.commit()
    await _mark_applied(conn, "M8.compliance_cleanup")
    print("✅ M8: compliance_cleanup completed")


async def _ensure_migrations_table(conn) -> None:
    """Defensive duplicate (создаётся в M1/M4/M5/M6/M7)."""
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

"""
Migration M35: Bannerlord clan upgrades — BLT-style система (Sprint 5.26a, 2026-05-21).

Зрители покупают долгосрочные баффы для своего клана за hero.gold:
+renown daily / +influence daily / +party size / +retinue size / +army speed.

Apgrades иерархические — T2 требует T1, T3 требует T2 (через
required_upgrade_id). Чтобы дойти до topa нужно пройти ветку.

Tables:
  bannerlord_clan_upgrades_catalog
    catalog default per channel (sееdится здесь, может расширяться runtime).
    - id, channel_id, upgrade_id (slug), name, description, tier, required_upgrade_id
    - gold_cost, effects_json (JSON: {renown_daily, influence_daily, ...})
    - deprecated, created_at

  bannerlord_clan_upgrades_owned
    Купленные апгрейды per viewer.
    - (channel_id, username, upgrade_id) PK
    - purchased_at, gold_paid

Стартовый seed (10 апгрейдов):
  T1: foundation_renown, foundation_influence, foundation_party
  T2: military_might, leadership_circle  (требуют T1)
  T3: warlord_renown, vassal_circle     (требуют T2)
  T4: imperial_might, master_general    (требуют T3)
  T5: legendary_status                  (требует T4)

Идемпотентно через migrations_applied['M35.clan_upgrades'].
"""
import json

CATALOG_SEED = [
    # (upgrade_id, name, description, tier, required_upgrade_id, gold_cost, effects)
    # ── Tier 1 (foundation) ──
    ('foundation_renown',  'Знамя клана',
     'Гордое знамя над станом — +1 renown/день', 1, None, 100_000,
     {'renown_daily': 1.0}),
    ('foundation_influence', 'Дипломатический корпус',
     'Послы наводят связи — +0.5 влияния/день', 1, None, 100_000,
     {'influence_daily': 0.5}),
    ('foundation_party', 'Усиленная свита',
     '+10 к лимиту party, +1 retinue slot', 1, None, 150_000,
     {'party_size_bonus': 10, 'retinue_size_bonus': 1}),
    # ── Tier 2 (требует T1) ──
    ('military_might', 'Военная мощь',
     '+2 renown/день, +15 party, +1 retinue', 2, 'foundation_party', 400_000,
     {'renown_daily': 2.0, 'party_size_bonus': 15, 'retinue_size_bonus': 1}),
    ('leadership_circle', 'Совет лидеров',
     '+1 влияния/день, +max parties +1', 2, 'foundation_influence', 400_000,
     {'influence_daily': 1.0, 'party_amount_bonus': 1}),
    # ── Tier 3 (требует T2) ──
    ('warlord_renown', 'Слава полководца',
     '+3 renown/день, +20 party, +1 retinue, +0.2 скорости', 3,
     'military_might', 900_000,
     {'renown_daily': 3.0, 'party_size_bonus': 20, 'retinue_size_bonus': 1,
      'party_speed_bonus': 0.2}),
    ('vassal_circle', 'Круг вассалов',
     '+2 влияния/день, +1 max vassals, +1 max parties', 3,
     'leadership_circle', 900_000,
     {'influence_daily': 2.0, 'max_vassals_bonus': 1, 'party_amount_bonus': 1}),
    # ── Tier 4 (требует T3) ──
    ('imperial_might', 'Имперская сила',
     '+4 renown/день, +25 party, +2 retinue, +0.3 army speed', 4,
     'warlord_renown', 1_800_000,
     {'renown_daily': 4.0, 'party_size_bonus': 25, 'retinue_size_bonus': 2,
      'army_speed_bonus': 0.3}),
    ('master_general', 'Главнокомандующий',
     '+3 влияния/день, +2 max vassals, +2 max parties', 4,
     'vassal_circle', 1_800_000,
     {'influence_daily': 3.0, 'max_vassals_bonus': 2, 'party_amount_bonus': 2}),
    # ── Tier 5 (требует T4 — capstone) ──
    ('legendary_status', 'Легендарный статус',
     '+5 renown, +5 влияния/день, +30 party, +3 retinue, +0.5 army speed',
     5, 'imperial_might', 3_500_000,
     {'renown_daily': 5.0, 'influence_daily': 5.0, 'party_size_bonus': 30,
      'retinue_size_bonus': 3, 'army_speed_bonus': 0.5}),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M35.clan_upgrades"):
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_clan_upgrades_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id          INTEGER NOT NULL,
            upgrade_id          TEXT NOT NULL,
            name                TEXT NOT NULL,
            description         TEXT,
            tier                INTEGER NOT NULL DEFAULT 1,
            required_upgrade_id TEXT,
            gold_cost           INTEGER NOT NULL,
            effects_json        TEXT NOT NULL DEFAULT '{}',
            deprecated          INTEGER NOT NULL DEFAULT 0,
            created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id, upgrade_id)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bnr_clan_upgrades_catalog_active
            ON bannerlord_clan_upgrades_catalog(channel_id, tier)
            WHERE deprecated = 0
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_clan_upgrades_owned (
            channel_id    INTEGER NOT NULL,
            username      TEXT NOT NULL,
            upgrade_id    TEXT NOT NULL,
            gold_paid     INTEGER NOT NULL,
            purchased_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, username, upgrade_id)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_bnr_clan_upgrades_owned_by_user
            ON bannerlord_clan_upgrades_owned(channel_id, username)
    """)

    # Seed catalog для всех зарегистрированных каналов (table 'channels').
    # Если таблица пустая / нет — fallback на дефолтный shedoy23 (98319857).
    channels = []
    try:
        cur = await conn.execute("SELECT id FROM channels")
        channels = [r[0] for r in await cur.fetchall() if r[0]]
    except Exception:
        pass
    if not channels:
        channels = [98319857]  # shedoy23 default

    for cid in channels:
        for upg in CATALOG_SEED:
            uid, name, desc, tier, req, cost, effects = upg
            await conn.execute(
                "INSERT OR IGNORE INTO bannerlord_clan_upgrades_catalog "
                "(channel_id, upgrade_id, name, description, tier, "
                " required_upgrade_id, gold_cost, effects_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, uid, name, desc, tier, req, cost, json.dumps(effects))
            )

    await conn.commit()
    await _mark_applied(conn, "M35.clan_upgrades")
    print(f"✅ M35: clan upgrades tables + seeded {len(CATALOG_SEED)} upgrades "
          f"для {len(channels)} channel(s)")


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

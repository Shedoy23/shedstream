"""Remove an advertised effect that has never been implemented."""
async def apply(conn):
    await conn.execute("UPDATE bannerlord_clan_upgrades_catalog SET effects_json=json_remove(effects_json,'$.max_vassals_bonus') WHERE json_valid(effects_json) AND json_type(effects_json,'$.max_vassals_bonus') IS NOT NULL")
    await conn.execute("UPDATE bannerlord_clan_upgrades_catalog SET description='Увеличивает ежедневное влияние и лимит отрядов клана.' WHERE upgrade_id IN ('vassal_circle','master_general')")
    await conn.execute("INSERT OR IGNORE INTO migrations_applied(name) VALUES ('M130.clan_catalog_truth')")
    await conn.commit()

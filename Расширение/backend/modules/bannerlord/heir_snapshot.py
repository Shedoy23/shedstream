"""Rebuild the heir mirror from complete game snapshots; caller owns transaction."""
async def reconcile_heir_snapshot(conn, channel_id, username, rows):
    if not isinstance(rows, list) or any(
        not isinstance(r, dict) or not isinstance(r.get("hero_id"), str)
        or not r["hero_id"].strip() or not isinstance(r.get("name"), str)
        for r in rows
    ):
        return
    # Missing or malformed snapshots must never erase older-client state.
    await conn.execute(
        "UPDATE bannerlord_heirs SET alive=0 WHERE channel_id=? AND parent_username=? AND activated=0",
        (channel_id, username))
    for row in rows:
        await conn.execute(
            "INSERT INTO bannerlord_heirs(channel_id,parent_username,heir_hero_id,heir_name,alive,activated) "
            "VALUES(?,?,?,?,?,0) ON CONFLICT(channel_id,heir_hero_id) DO UPDATE SET "
            "heir_name=excluded.heir_name,alive=excluded.alive "
            "WHERE bannerlord_heirs.parent_username=excluded.parent_username",
            (channel_id, username, row["hero_id"], row["name"], int(bool(row.get("alive", True)))))

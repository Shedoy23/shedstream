"""
modules/bannerlord/_adapter.py — BannerlordAdapter (Sprint 1.2 real handlers).

Sprint 1.2 status:
  ✅ Lifecycle (session_start/end/heartbeat) — реализовано
  ✅ Catalog update — generic, переиспользует module_catalogs
  ✅ Player events (linked/unlinked/state_update/died/respawned) — writes
     в bannerlord_heroes / bannerlord_skills / bannerlord_attributes /
     bannerlord_equipment + audit log
  ✅ Extension events (hero.skill_changed / hero.equipment_changed /
     hero.relation_changed / hero.faction_changed) — updates relevant таблицы
  ✅ world.event_occurred — log в bannerlord_events_log + TG notify
     для major events (siege_won, settlement_captured)
  ✅ dispatch_action — enqueue в generic module_actions outbox

C# mod (Sprint 2+) будет:
  - POST events на /v1/module/bannerlord/events
  - Long-poll /v1/module/bannerlord/actions для action queue
  - ACK исполнения POST /v1/module/bannerlord/ack
Routing logic — общий `routes/module_api.py`, никакой Bannerlord-specific
core-кодовой правки не требуется (Module API game-agnostic).

См. docs/BANNERLORD_MVP.md §1-§3 для events/actions mapping.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from .._base import ModuleAdapter, ModuleEnvelope

logger = logging.getLogger("rimlink.modules.bannerlord")

# In-memory last-seen tracking per channel — для UI online badge.
# Заполняется каждым event (любой type → mod alive). Frontend читает через
# GET /api/bannerlord/status. Reset на supervisor restart, что OK (mod пошлёт
# session_start при следующем боте подключении).
_last_seen: dict = {}  # {channel_id: unix_timestamp}

# Sprint 4.6: in-memory active buffs per viewer. Backend получает события
# buff.activated/buff.expired от мода и хранит remaining time для frontend
# HUD. Reset на restart — mod при следующей активации пошлёт buff.activated
# повторно (или buff истечёт raw, mod пушнёт buff.expired). Acceptable.
#   {(channel_id, username): {power_key: expires_at_unix}}
_active_buffs: dict = {}

# Sprint 4.8: in-memory cooldowns per viewer для active powers. Server-side
# enforcement (frontend disable — только UX, не security). Set'ится при
# successful /api/bannerlord/action для power.activate. Reset на restart —
# OK (viewer получит "бесплатный" cooldown skip, не критично).
#   {(channel_id, username): {power_key: cooldown_expires_at_unix}}
_cooldowns: dict = {}

# Cooldown seconds для каждого active power_key. Tuned for live stream
# pacing — поправим в 4.10 после feedback. Хардкод чтобы не плодить миграции
# на mvp scale; рефакторим в админку когда понадобится per-streamer балансинг.
POWER_COOLDOWNS = {
    "heal_burst":          30,
    "shield_break_burst":  90,
    "rage":                60,
    "retribution_toggle":  90,
}


def update_last_seen(channel_id: int) -> None:
    """Обновить last-seen timestamp для канала."""
    import time
    _last_seen[channel_id] = time.time()


def get_last_seen(channel_id: int) -> float:
    """Возвращает unix timestamp последнего event'а или 0 если не было."""
    return _last_seen.get(channel_id, 0.0)


def get_active_buffs(channel_id: int, username: str) -> list:
    """Возвращает [{power_key, remaining_s}] для viewer'а. Expired drop'аются.

    Frontend читает через GET /api/bannerlord/my-buffs каждые ~2 сек,
    decrement'ит remaining client-side между poll'ами (smooth countdown).
    """
    import time
    key = (channel_id, (username or "").lower())
    perViewer = _active_buffs.get(key)
    if not perViewer:
        return []
    now = time.time()
    out = []
    expired = []
    for power_key, exp_at in perViewer.items():
        rem = exp_at - now
        if rem <= 0:
            expired.append(power_key)
        else:
            out.append({"power_key": power_key, "remaining_s": round(rem, 1)})
    for pk in expired:
        perViewer.pop(pk, None)
    if not perViewer:
        _active_buffs.pop(key, None)
    return out


def get_active_cooldowns(channel_id: int, username: str) -> list:
    """[{power_key, remaining_s}] для viewer'а. Sprint 4.8."""
    import time
    key = (channel_id, (username or "").lower())
    perViewer = _cooldowns.get(key)
    if not perViewer:
        return []
    now = time.time()
    out = []
    expired = []
    for power_key, exp_at in perViewer.items():
        rem = exp_at - now
        if rem <= 0:
            expired.append(power_key)
        else:
            out.append({"power_key": power_key, "remaining_s": round(rem, 1)})
    for pk in expired:
        perViewer.pop(pk, None)
    if not perViewer:
        _cooldowns.pop(key, None)
    return out


def check_cooldown(channel_id: int, username: str, power_key: str) -> float:
    """Возвращает remaining seconds (>0 → on cooldown), 0 если можно activate.

    Sprint 4.8. /api/bannerlord/action вызывает перед charge.
    """
    import time
    key = (channel_id, (username or "").lower())
    perViewer = _cooldowns.get(key)
    if not perViewer:
        return 0.0
    exp_at = perViewer.get(power_key)
    if exp_at is None:
        return 0.0
    rem = exp_at - time.time()
    if rem <= 0:
        perViewer.pop(power_key, None)
        return 0.0
    return rem


def set_cooldown(channel_id: int, username: str, power_key: str) -> None:
    """Запустить cooldown для power_key. Длительность из POWER_COOLDOWNS.

    Sprint 4.8. Вызывается после successful enqueue power.activate в /action.
    Если power_key не в POWER_COOLDOWNS — no-op (e.g. unknown power).
    """
    import time
    cd_seconds = POWER_COOLDOWNS.get(power_key)
    if not cd_seconds:
        return
    key = (channel_id, (username or "").lower())
    _cooldowns.setdefault(key, {})[power_key] = time.time() + cd_seconds


# Events которые triggrят TG-нотификацию (major world events).
# Не каждое event_occurred — это спам. Только заметные исходы.
_TG_TRIGGER_EVENTS = (
    "settlement_captured",
    "settlement_lost",
    "lord_killed",
    "lord_captured",
    "siege_won",
    "siege_lost",
    "tournament_won",
)


class BannerlordAdapter(ModuleAdapter):
    """Bannerlord-specific module adapter."""

    # ── Event dispatcher ──────────────────────────────────────────────────────

    async def handle_event(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Dispatch по env.type. Module API §7 standard + manifest extensions."""
        et = env.type

        # Update last-seen для любого event — mod alive (for UI online badge).
        update_last_seen(channel_id)

        if et == "module.heartbeat":
            return  # no-op (но last-seen уже обновлён выше)

        if et == "module.session_start":
            await self._on_session_start(channel_id, env)
            return

        if et == "module.session_end":
            print(f"[bannerlord:{channel_id}] session_end "
                  f"reason={env.data.get('reason', 'graceful')}")
            return

        if et == "module.catalog_update":
            await self._on_catalog_update(channel_id, env)
            return

        # ── Standard player events ─────────────────────────────────────────
        if et == "player.linked":
            await self._on_player_linked(channel_id, env)
            return

        if et == "player.unlinked":
            await self._on_player_unlinked(channel_id, env)
            return

        if et == "player.state_update":
            await self._on_player_state_update(channel_id, env)
            return

        if et == "player.died":
            await self._on_player_died(channel_id, env)
            return

        if et == "player.respawned":
            await self._on_player_respawned(channel_id, env)
            return

        # ── Bannerlord extension events ────────────────────────────────────
        if et == "hero.skill_changed":
            await self._on_skill_changed(channel_id, env)
            return

        if et == "hero.equipment_changed":
            await self._on_equipment_changed(channel_id, env)
            return

        if et in ("hero.relation_changed", "hero.faction_changed"):
            # Cosmetic-only, log only пока (не влияет на game-state в backend)
            await self._log_event(channel_id, et, env.data.get("username"), env.data)
            return

        if et == "buff.activated":
            await self._on_buff_activated(channel_id, env)
            return

        if et == "buff.expired":
            await self._on_buff_expired(channel_id, env)
            return

        if et == "world.event_occurred":
            await self._on_world_event(channel_id, env)
            return

        # Unknown — manifest.supports_event уже отверг бы в routes/module_api.py
        logger.warning("[bannerlord:%s] unhandled event type=%s", channel_id, et)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def _on_session_start(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Чистим session-scoped catalogs (MULTITENANT_PLAN §H pattern).

        Heroes / skills / equipment — НЕ чистим: они persistent across
        sessions (зритель сохраняет hero даже если стример перезагрузил save).
        """
        save_id = env.data.get("save_id", "")
        from dependencies import get_db
        cleared = await get_db().clear_module_catalogs(channel_id, self.id)
        print(f"[bannerlord:{channel_id}] session_start save_id={save_id} "
              f"(cleared {cleared} catalog entries)")

    async def _on_catalog_update(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Generic catalog write. Catalog types declared в manifest.yaml."""
        catalog_type = str(env.data.get("catalog") or "").lower()
        if catalog_type not in ("shop", "events"):
            logger.warning("[bannerlord:%s] catalog_update unknown type=%s",
                           channel_id, catalog_type)
            return
        entries = env.data.get("entries") or []
        if not isinstance(entries, list):
            return
        from dependencies import get_db
        inserted = await get_db().replace_module_catalog(
            channel_id=channel_id,
            module_id=self.id,
            catalog_type=catalog_type,
            entries=entries,
        )
        print(f"[bannerlord:{channel_id}] catalog_update: type={catalog_type} "
              f"entries={inserted} (replaced)")

    # ── Player events ─────────────────────────────────────────────────────────

    async def _on_player_linked(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Зритель adopt'ил NPC hero. Upsert row."""
        data = env.data
        username = (data.get("username") or "").lower()
        hero_id = data.get("hero_id") or ""
        display_name = data.get("display_name") or username or hero_id
        culture = data.get("culture")

        if not username or not hero_id:
            logger.warning("[bannerlord:%s] player.linked missing username/hero_id: %s",
                           channel_id, data)
            return

        from dependencies import get_db
        async with get_db()._connect() as conn:
            # ON CONFLICT (channel_id, username) — re-adopt (после heir) обновляет hero_id
            await conn.execute("""
                INSERT INTO bannerlord_heroes
                    (channel_id, username, hero_id, display_name, culture, is_alive)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(channel_id, username) DO UPDATE SET
                    hero_id      = excluded.hero_id,
                    display_name = excluded.display_name,
                    culture      = COALESCE(excluded.culture, culture),
                    is_alive     = 1,
                    is_prisoner  = 0,
                    last_sync    = CURRENT_TIMESTAMP
            """, (channel_id, username, hero_id, display_name, culture))
            await conn.commit()

        await self._log_event(channel_id, "player.linked", username, data)
        print(f"[bannerlord:{channel_id}] player.linked @{username} → hero={hero_id}")

    async def _on_player_unlinked(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Admin-action: открепить hero от зрителя. Удаляем row + связанные."""
        username = (env.data.get("username") or "").lower()
        if not username:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            for tbl in ("bannerlord_skills", "bannerlord_attributes",
                         "bannerlord_equipment", "bannerlord_heroes"):
                await conn.execute(
                    f"DELETE FROM {tbl} WHERE channel_id=? AND username=?",
                    (channel_id, username))
            await conn.commit()
        await self._log_event(channel_id, "player.unlinked", username, env.data)

    async def _on_player_state_update(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod synced состояние hero (gold, location, alive/prisoner status)."""
        data = env.data
        username = (data.get("username") or "").lower()
        if not username:
            return

        fields = []
        params: list = []
        for k in ("gold", "is_alive", "is_prisoner", "location"):
            if k in data:
                fields.append(f"{k} = ?")
                params.append(data[k])
        if not fields:
            return
        fields.append("last_sync = CURRENT_TIMESTAMP")
        params.extend([channel_id, username])

        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                f"UPDATE bannerlord_heroes SET {', '.join(fields)} "
                f"WHERE channel_id=? AND username=?",
                params)
            await conn.commit()

    async def _on_player_died(self, channel_id: int, env: ModuleEnvelope) -> None:
        """HeroKilled event. Mark dead + audit. Heir succession — Sprint 1.3+."""
        data = env.data
        username = (data.get("username") or "").lower()
        if not username:
            return

        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET is_alive=0, last_sync=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))
            await conn.commit()

        await self._log_event(channel_id, "player.died", username, data)
        print(f"[bannerlord:{channel_id}] @{username} hero died "
              f"killer={data.get('killer_name', 'unknown')}")

        # TODO Sprint 1.3+: auto-heir assignment
        #   - find free unadopted NPC hero from pool
        #   - enqueue player.respawn action в action queue → mod исполнит
        #   - update bannerlord_heroes с new hero_id, is_alive=1

    async def _on_player_respawned(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Heir succession completed — mod подтвердил respawn на новом hero."""
        data = env.data
        username = (data.get("username") or "").lower()
        new_hero_id = data.get("hero_id") or ""
        if not username or not new_hero_id:
            return

        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET hero_id=?, is_alive=1, is_prisoner=0, "
                "last_sync=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND username=?",
                (new_hero_id, channel_id, username))
            await conn.commit()

        await self._log_event(channel_id, "player.respawned", username, data)
        print(f"[bannerlord:{channel_id}] @{username} respawned as hero={new_hero_id}")

    # ── Extension events ──────────────────────────────────────────────────────

    async def _on_skill_changed(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Hero leveled up skill / gained xp."""
        data = env.data
        username = (data.get("username") or "").lower()
        skill_key = (data.get("skill_key") or "").lower()
        level = data.get("level")
        xp = data.get("xp", 0)
        if not username or not skill_key or level is None:
            return

        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute("""
                INSERT INTO bannerlord_skills (channel_id, username, skill_key, level, xp)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(channel_id, username, skill_key) DO UPDATE SET
                    level = excluded.level,
                    xp    = excluded.xp
            """, (channel_id, username, skill_key, int(level), int(xp)))
            await conn.commit()

    async def _on_equipment_changed(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Hero equipped/unequipped item."""
        data = env.data
        username = (data.get("username") or "").lower()
        slot = (data.get("slot") or "").lower()
        item_id = data.get("item_id")  # None = unequipped
        item_name = data.get("item_name")
        if not username or not slot:
            return

        from dependencies import get_db
        async with get_db()._connect() as conn:
            if item_id:
                await conn.execute("""
                    INSERT INTO bannerlord_equipment
                        (channel_id, username, slot, item_id, item_name)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(channel_id, username, slot) DO UPDATE SET
                        item_id   = excluded.item_id,
                        item_name = excluded.item_name
                """, (channel_id, username, slot, item_id, item_name))
            else:
                # Unequipped — удаляем row
                await conn.execute(
                    "DELETE FROM bannerlord_equipment "
                    "WHERE channel_id=? AND username=? AND slot=?",
                    (channel_id, username, slot))
            await conn.commit()

    # ── Buff events (Sprint 4.6) ──────────────────────────────────────────────

    async def _on_buff_activated(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod активировал active buff (rage/retribution_toggle) для зрителя.

        Хранится только in-memory: state живёт в C# моде (источник истины),
        мы тут — кэш для frontend HUD. На expiry или mission end mod пушнёт
        buff.expired.
        """
        import time
        data = env.data
        username = (data.get("username") or "").lower()
        power_key = (data.get("power_key") or "").lower()
        duration_s = float(data.get("duration_s") or 0)
        if not username or not power_key or duration_s <= 0:
            return
        expires_at = time.time() + duration_s
        key = (channel_id, username)
        _active_buffs.setdefault(key, {})[power_key] = expires_at
        await self._log_event(channel_id, "buff.activated", username, data)

    async def _on_buff_expired(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod сообщил что buff истёк. Удаляем из in-memory store."""
        data = env.data
        username = (data.get("username") or "").lower()
        power_key = (data.get("power_key") or "").lower()
        if not username or not power_key:
            return
        key = (channel_id, username)
        perViewer = _active_buffs.get(key)
        if perViewer:
            perViewer.pop(power_key, None)
            if not perViewer:
                _active_buffs.pop(key, None)
        await self._log_event(channel_id, "buff.expired", username, data)

    # ── World events ──────────────────────────────────────────────────────────

    async def _on_world_event(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Global Bannerlord events (battle, siege, settlement, tournament).

        Log в audit + TG notify для major events.
        """
        data = env.data
        kind = (data.get("kind") or "unknown").lower()
        await self._log_event(channel_id, f"world.{kind}", data.get("username"), data)

        if kind in _TG_TRIGGER_EVENTS:
            # Lazy import чтобы не циклить notifications ↔ modules
            try:
                from notifications import notify_world_event
                await notify_world_event(channel_id=channel_id, kind=kind, data=data)
            except ImportError:
                pass  # notify_world_event ещё не написан (Sprint 1.6)
            except Exception as e:
                logger.warning("[bannerlord:%s] TG world event notify failed: %s",
                               channel_id, e)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _log_event(
        self,
        channel_id: int,
        event_type: str,
        username: Optional[str],
        data: Dict[str, Any],
    ) -> None:
        """Append-only audit log в bannerlord_events_log."""
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute("""
                INSERT INTO bannerlord_events_log
                    (channel_id, event_type, username, payload)
                VALUES (?, ?, ?, ?)
            """, (channel_id, event_type, username, json.dumps(data, ensure_ascii=False)))
            await conn.commit()

    # ── Action dispatch ───────────────────────────────────────────────────────

    async def dispatch_action(self, channel_id: int, env: ModuleEnvelope) -> Dict[str, Any]:
        """Enqueue в generic module_actions outbox.

        C# mod long-poll'ит `GET /v1/module/bannerlord/actions` и забирает.
        После исполнения POST /v1/module/bannerlord/ack {action_id, success}.

        Validation: action type должен быть declared в manifest.actions/extensions.
        """
        if not self.manifest.supports_action(env.type):
            return {
                "queued": False,
                "reason": "action_not_in_manifest",
                "action_id": env.id,
                "type": env.type,
            }
        from dependencies import get_db
        pk = await get_db().enqueue_action(
            channel_id=channel_id,
            module_id=self.id,
            action_id=env.id,
            action_type=env.type,
            data=env.data,
        )
        return {
            "queued":    True,
            "action_id": env.id,
            "outbox_pk": pk,
            "module_id": self.id,
        }

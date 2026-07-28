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

# Sprint 5.4: in-memory snapshot активных summoned heroes в Mission.
# Mod пушит battle.stats_snapshot каждые ~1.5с. Overlay polls and renders
# (HP bar / kills / gold / xp).
#   {channel_id: {
#       'final': bool,          # True если Mission ended
#       'updated_at': unix_ts,
#       'participants': [{username, hp, hp_max, alive, kills, gold_earned, xp_earned}],
#   }}
_battle_stats: dict = {}
# Sec, после которого snapshot считается stale → overlay скрывает карточки.
_BATTLE_STATS_TTL = 8.0

# Cooldown seconds для каждого active power_key. Tuned for live stream
# pacing — поправим в 4.10 после feedback. Хардкод чтобы не плодить миграции
# на mvp scale; рефакторим в админку когда понадобится per-streamer балансинг.
# Также используется как cooldown для action_types (summon).
POWER_COOLDOWNS = {
    # 2026-06-01 — все активные способности унифицированы: cooldown 90с.
    # Длительность баффов (45с) задаётся мод-сайдом (ActivatePowerHandler).
    "heal_burst":          90,
    "shield_break_burst":  90,
    "rage":                90,
    "retribution_toggle":  90,
    "cleave":              90,   # 2026-06-17 (#15) — мили AoE-активка
    # Sprint 5.0: player.spawn = summon hero в Mission. Cooldown особо нужен —
    # spawn в идущий бой это серьёзное вмешательство, нельзя спамить.
    # Sprint 5.27i: 120s → 30s (быстрее ротация участников).
    # Sprint 5.29: split per side — player.spawn:player vs player.spawn:enemy.
    # (summon — НЕ ability, оставляем свои значения.)
    "player.spawn":          30,   # legacy fallback (если side не передан)
    "player.spawn:player":   30,   # ally — viewer на стороне стримера
    "player.spawn:enemy":    45,   # enemy — slightly longer, чтобы не спамили против
    # Sprint 5.33 (BLT-parity FX) — character effects (BLT-Buffet inspired).
    "poison_dot":          90,
    "disarm_burst":        90,
    "berserker_charge":    90,
    # 2026-05-29 (BLT-parity combat powers) — active burst-варианты.
    "lifesteal_burst":     90,
    "ironskin_toggle":     90,
    "explosive_arrows":    90,
}

# Sprint 5.29 audit fix #28 — anti-spam cooldowns per (channel, user, action_type).
# Раньше cooldown был ТОЛЬКО на power.activate и player.spawn. Spam-prone actions
# (recruit / heal / equip / add_skill / add_focus / add_attribute / marry / etc.)
# можно было spam'ить кнопками в overlay → backend ack'ал каждое сразу,
# крустики списывались, действие шло. Теперь — soft rate-limit per user.
#
# Values — short enough to не мешать legit use, long enough чтобы блокировать
# рапидный clicker.
ACTION_COOLDOWNS_SEC = {
    "player.heal":               5,    # quick combat use
    "player.equip_item":        15,
    "player.modify_attribute":  20,
    "hero.add_skill":            3,
    "hero.add_focus":           10,
    "hero.add_attribute":       30,
    "hero.recruit_troops":      10,
    "hero.train_troops":        30,    # 2026-05-29 BLT TrainingBehavior — bulk-upgrade свиты
    "hero.upgrade_gear":        30,
    "hero.reequip_gear":        30,    # 2026-05-29 re-roll снаряги (anti-spam fishing)
    "hero.set_class":           60,
    "hero.marry":              180,    # heavy lore-action, 3 min
    "hero.divorce":             60,
    "hero.make_baby":          300,    # 5 min
    "hero.set_gender":         300,
    "hero.create_clan":        600,    # 10 min — серьёзное действие
    "hero.create_kingdom":    1200,    # 20 min — очень серьёзное
    "hero.create_party":       600,
    "hero.leave_clan":          60,
    "hero.leave_kingdom":       60,
    "hero.join_clan":          120,
    "hero.join_kingdom":       120,
    "hero.join_tournament":     30,    # хочется быстрая re-queue после поражения
    "world.trigger_event":    3600,    # admin-style, 1h
    # Sprint 5.32 (BLT-parity H3) — добавлены недостающие actions для full coverage.
    # Без этих entry'ев curl bypass обходил throttle для adopt-spam, smith-spam,
    # bet-spam, trophy-spam. Главные actions уже покрыты выше (audit-fix #28).
    "hero.create":              60,    # adoption — viewer спамит /adopt пока не зайдёт «redeem»
    "hero.smith_item":          30,    # crafting — economy-heavy
    "hero.equip_trophy":         5,    # equip/unequip toggle
    "tournament.predict":        3,    # game-logic уже dedup'ит по round_index; safety-net против multi-target spam
    # NB: power.activate cooldown идёт через POWER_COOLDOWNS (per-power_key),
    #     player.spawn — через POWER_COOLDOWNS["player.spawn:<side>"].
    #     Эти actions НЕ нужно дублировать здесь.
    # Sprint 5.32 (BLT-parity Detachment) — короткий cooldown 2s чтобы viewer
    # мог реагировать на изменение боя ("противник прорвался к gate'у —
    # сменю hold на charge"), но не спамил кликами для двойного списания.
    "hero.detach":               2,
    "hero.attach":                2,
    "hero.detach_hold":           2,
    "hero.detach_charge":         2,
    "hero.detach_skirmish":       2,    # 2026-06-17 рич-приказ — бой-на-расстоянии
    "hero.detach_raid":           2,    # 2026-06-17 рич-приказ — конная орбита
    "hero.detach_walls":          3,    # siege — re-issue takes engine моменты
    "hero.detach_gate":           3,
    # Sprint 5.33 (BLT-parity FAM) — anti-spam для семейных интеракций.
    # Propose 60s — нельзя зафлудить таргета. Rest — short.
    "hero.propose_marriage":         60,
    "hero.respond_marriage_proposal": 3,
    "hero.cancel_proposal":           5,
    "hero.rename_child":             10,
    "hero.change_child_looks":       30,
    "hero.respec_child_skills":     120,
    # Sprint 5.33 (BLT-parity VAS) — vassal sub-clan management
    "hero.create_vassal_clan":      300,   # heavy state mutation, не спам
    "hero.recruit_vassal_clan":     300,   # 2026-06-17: тяжёлое создание NPC-клана, не спам
    "hero.rename_vassal":            30,
    # Sprint 5.33 (BLT-parity SIEGE) — party orders
    "hero.party_order_set":         120,   # значительное решение, anti-spam
    "hero.party_order_release":      10,
    # Sprint 5.33 (BLT-parity DIPLO) — kingdom politics + ransom
    "hero.enact_policy":            300,   # heavy political decision, anti-spam
    "hero.make_peace":              600,   # huge decision, hard cooldown
    "hero.pay_ransom":               20,   # short — many viewers can chip in
    # 2026-06-14 — дипломатия через голосование кланов. Per-viewer anti-spam:
    # одно предложение войны/мира раз в 5 мин (движок и так сериализует голоса,
    # дубль по таргету отсекается отдельно; это против спама одним зрителем).
    "kingdom.propose_war":          300,
    "kingdom.propose_peace":        300,
    # Sprint 5.33 (BLT-parity SHOP) — workshops passive income
    "hero.buy_workshop":            120,   # economic decision, no spam
    "hero.sell_workshop":            60,
    # Sprint 5.33 (BLT-parity FIEF) — tribute boost (7-day duration anyway)
    "hero.tribute_boost":           120,   # короткий cd — boost cap есть в handler'е
    # Sprint 5.33 (BLT-parity CARAVAN) — mobile passive income
    "hero.buy_caravan":             180,   # economic decision, mid cooldown
    "hero.sell_caravan":             60,
}


# Sprint 5.33 IMPROV-1 — background cleanup для stale streamer channels.
# Friend feedback: "если стример offline 10+ минут — лайф кеш зачищаем".
# Без этого: in-memory dicts (_battle_stats, _active_buffs, _cooldowns) растут
# unbounded когда streamer'ы приходят и уходят. Хоть entries уже expire'ятся
# lazily при чтении — для caнаlov которые НЕ читают NEXT раз (e.g. streamer
# больше никогда не запустит) garbage висит до process restart.
#
# Loop: каждые CLEANUP_INTERVAL_SEC проходит по _last_seen, finds entries
# где last_seen < now - STALE_THRESHOLD_SEC, dropит соответствующие entries
# из всех cache dicts.
STALE_THRESHOLD_SEC = 600    # 10 минут — friend's recommendation
CLEANUP_INTERVAL_SEC = 60    # проверять раз в минуту


async def stale_channels_cleanup_loop():
    """Background task. Запускается в main.py lifespan handler."""
    import asyncio
    import time as _time
    import logging
    log = logging.getLogger(__name__)

    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SEC)
            now = _time.time()

            # 1) Find stale channel_id's.
            stale_channels = []
            for ch_id, last_ts in list(_last_seen.items()):
                if now - last_ts > STALE_THRESHOLD_SEC:
                    stale_channels.append(ch_id)

            if not stale_channels:
                continue

            # 2) Drop entries from all in-memory caches.
            stats_dropped = 0
            buffs_dropped = 0
            cds_dropped = 0
            last_seen_dropped = 0

            for ch_id in stale_channels:
                # _battle_stats keyed by channel_id directly
                if _battle_stats.pop(ch_id, None) is not None:
                    stats_dropped += 1
                # _last_seen — drop последним чтобы logger знал ch_id
                if _last_seen.pop(ch_id, None) is not None:
                    last_seen_dropped += 1

            # _active_buffs / _cooldowns — keyed by (channel_id, username) tuple
            stale_set = set(stale_channels)
            for key in list(_active_buffs.keys()):
                if isinstance(key, tuple) and key[0] in stale_set:
                    _active_buffs.pop(key, None)
                    buffs_dropped += 1
            for key in list(_cooldowns.keys()):
                if isinstance(key, tuple) and key[0] in stale_set:
                    _cooldowns.pop(key, None)
                    cds_dropped += 1

            # Sprint 5.30 #41 — _power_events ring buffer per-channel. Tоже cleanup.
            try:
                from routes.bannerlord import _power_events, _power_events_seq
                pe_dropped = 0
                for ch_id in stale_channels:
                    if _power_events.pop(ch_id, None) is not None:
                        pe_dropped += 1
                    _power_events_seq.pop(ch_id, None)
            except Exception:
                pe_dropped = 0

            log.info(
                "[BNR CLEANUP] %d stale channels (>%ds offline) — "
                "dropped %d battle_stats, %d active_buffs, %d cooldowns, "
                "%d power_event_buffers, %d last_seen entries",
                len(stale_channels), STALE_THRESHOLD_SEC,
                stats_dropped, buffs_dropped, cds_dropped,
                pe_dropped if 'pe_dropped' in dir() else 0,
                last_seen_dropped)

        except asyncio.CancelledError:
            log.info("[BNR CLEANUP] task cancelled (shutdown)")
            raise
        except Exception as ex:
            # Никогда не давать упасть loop'у — log + sleep + продолжать
            log.exception("[BNR CLEANUP] loop iteration crashed: %s", ex)
            await asyncio.sleep(CLEANUP_INTERVAL_SEC)


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
    """Запустить cooldown для power_key. Длительность из POWER_COOLDOWNS либо
    ACTION_COOLDOWNS_SEC (fallback).

    Sprint 4.8 — power.activate.
    Sprint 5.29 audit fix #28 — extended на action_type'ы (spam protection).
    Если key не в обоих dict'ах — no-op.
    """
    import time
    cd_seconds = POWER_COOLDOWNS.get(power_key) or ACTION_COOLDOWNS_SEC.get(power_key)
    if not cd_seconds:
        return
    key = (channel_id, (username or "").lower())
    _cooldowns.setdefault(key, {})[power_key] = time.time() + cd_seconds


def get_battle_stats(channel_id: int) -> dict:
    """Возвращает snapshot активного боя для overlay. Если stale (>TTL) —
    возвращает пустой dict (overlay скрывает карточки)."""
    import time as _time
    snap = _battle_stats.get(channel_id)
    if not snap:
        return {"active": False, "participants": []}
    age = _time.time() - snap.get("updated_at", 0)
    if age > _BATTLE_STATS_TTL or snap.get("final"):
        # Final ИЛИ stale — overlay скрывает (battle закончился / pause)
        return {
            "active":       False,
            "final":        snap.get("final", False),
            "participants": snap.get("participants", []),
            "age_sec":      round(age, 1),
        }
    return {
        "active":       True,
        "final":        False,
        "participants": snap.get("participants", []),
        "age_sec":      round(age, 1),
    }


def get_my_battle_stats(channel_id: int, username: str) -> dict:
    """Sprint 5.5: для viewer extension. Возвращает только МОИ stats
    + флаг in_battle. Использует тот же snapshot что и overlay."""
    snap = get_battle_stats(channel_id)
    in_battle = snap.get("active", False)
    my = None
    if in_battle and username:
        u = username.lower()
        for p in snap.get("participants", []):
            if (p.get("username") or "").lower() == u:
                my = p
                break
    return {
        "in_battle":         in_battle,
        "participant_count": len(snap.get("participants", [])) if in_battle else 0,
        "my_stats":          my,
    }


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

        if et in ("hero.relation_changed", "hero.faction_changed",
                  "hero.marriage_activated"):
            # Cosmetic-only, log only пока (не влияет на game-state в backend)
            await self._log_event(channel_id, et, env.data.get("username"), env.data)
            return

        if et == "buff.activated":
            await self._on_buff_activated(channel_id, env)
            return

        if et == "buff.expired":
            await self._on_buff_expired(channel_id, env)
            return

        if et == "hero.gear_tier_changed":
            await self._on_gear_tier_changed(channel_id, env)
            return

        if et == "hero.restore_profile":
            await self._on_restore_profile(channel_id, env)
            return

        if et == "hero.restore_clan_upgrades":
            await self._on_restore_clan_upgrades(channel_id, env)
            return

        if et == "module.heroes_snapshot":
            await self._on_heroes_snapshot(channel_id, env)
            return

        if et == "hero.retinue_changed":
            await self._on_retinue_changed(channel_id, env)
            return

        if et == "hero.retinue_casualty":
            await self._on_retinue_casualty(channel_id, env)
            return

        if et == "hero.focus_changed":
            await self._on_focus_changed(channel_id, env)
            return

        if et == "hero.attribute_changed":
            await self._on_attribute_changed(channel_id, env)
            return

        if et == "hero.clan_created":
            await self._on_clan_created(channel_id, env)
            return

        # Sprint 5.29 audit fix #33 — 6 manifest events для clan/kingdom/party
        if et == "hero.clan_joined":
            await self._on_clan_joined(channel_id, env)
            return
        if et == "hero.clan_left":
            await self._on_clan_left(channel_id, env)
            return
        if et == "hero.kingdom_created":
            await self._on_kingdom_created(channel_id, env)
            return
        if et == "hero.kingdom_joined":
            await self._on_kingdom_joined(channel_id, env)
            return
        if et == "hero.kingdom_left":
            await self._on_kingdom_left(channel_id, env)
            return
        if et == "hero.party_created":
            await self._on_party_created(channel_id, env)
            return

        # ── Sprint 5.4: Battle stats snapshot (для overlay) ────────────────
        if et == "battle.stats_snapshot":
            self._on_battle_stats(channel_id, env)
            return

        # ── Sprint 5.3: Tournament events ──────────────────────────────────
        if et == "tournament.joined":
            await self._on_tournament_joined(channel_id, env)
            return

        if et == "tournament.left":
            await self._on_tournament_left(channel_id, env)
            return

        if et == "tournament.started":
            await self._on_tournament_started(channel_id, env)
            return

        if et == "tournament.round_ended":
            await self._on_tournament_round_ended(channel_id, env)
            return

        if et == "tournament.ended":
            await self._on_tournament_ended(channel_id, env)
            return

        # Sprint 5.32 (BLT-parity M2) — heir queue foundation.
        if et == "hero.heir_came_of_age":
            await self._on_heir_came_of_age(channel_id, env)
            return
        if et == "hero.heir_died":
            await self._on_heir_died(channel_id, env)
            return

        # Sprint 5.33 (BLT-parity VAS) — vassal lifecycle events
        if et == "hero.vassal_created":
            await self._on_vassal_created(channel_id, env)
            return

        # Sprint 5.33 (BLT-parity SHOP) — workshop daily profit sync
        if et == "hero.workshop_profit_sync":
            await self._on_workshop_profit_sync(channel_id, env)
            return

        # Sprint 5.33 (BLT-parity FIEF) — fief tribute daily sync
        if et == "hero.fief_tribute_sync":
            await self._on_fief_tribute_sync(channel_id, env)
            return

        # Sprint 5.33 (BLT-parity CARAVAN) — caravan lifecycle (3 events)
        if et == "hero.caravan_created":
            await self._on_caravan_created(channel_id, env)
            return
        if et == "hero.caravan_profit_sync":
            await self._on_caravan_profit_sync(channel_id, env)
            return
        if et == "hero.caravan_destroyed":
            await self._on_caravan_destroyed(channel_id, env)
            return

        # 2026-06-02 (PROPERTIES-MIRROR) — игра = источник правды. Полный
        # snapshot владений ([BLink]-герои сейчас) → backend зеркалит.
        if et == "hero.properties_snapshot":
            await self._on_properties_snapshot(channel_id, env)
            return

        if et == "world.event_occurred":
            await self._on_world_event(channel_id, env)
            return

        # Sprint 5.33 PORDER — sticky party-order lifecycle status push.
        # Mod пушит при set/release/expire/complete (auto-detected).
        if et == "hero.party_order_status":
            await self._on_party_order_status(channel_id, env)
            return

        # Sprint 5.33 CATALOG-1 — live settlements catalog from mod (towns/
        # villages/castles + faction info) → backend cache → extension dropdown.
        if et == "world.settlements_catalog":
            await self._on_settlements_catalog(channel_id, env)
            return

        # Sprint 5.29 / BLT-parity #3: refund крустиков на отказ мода
        if et == "action.failed":
            await self._on_action_failed(channel_id, env)
            return

        # 2026-07-22 (багрепорт #23): итог заявки на закон королевства.
        if et == "hero.policy_result":
            await self._on_policy_result(channel_id, env)
            return

        # Unknown — manifest.supports_event уже отверг бы в routes/module_api.py
        logger.warning("[bannerlord:%s] unhandled event type=%s", channel_id, et)

    async def _on_policy_result(self, channel_id: int, env: ModuleEnvelope) -> None:
        """2026-07-22 (багрепорт #23) — закрыть заявку на закон по факту.

        Было: статус заявки не обновлял НИКТО (ни одного UPDATE в кодовой базе).
        Все 16 заявок на проде висели 'pending' — при том, что лог игры
        показывает 16 из 16 применённых законов. Зритель платил 1500💎, закон
        в игре действовал, а расширение вечно показывало «на голосовании» и
        больше не давало нажать: уникальный индекс пускает лишь одну pending-
        заявку на (канал, королевство, закон). Отменить закон тоже было нельзя.

        ACK от ActionPoller здесь не помощник — он приходит success=true ещё до
        реальной работы. Поэтому мод шлёт отдельный итог.

        env.data: {action_id: str, policy_id: str, enacted: bool}
        """
        data = env.data or {}
        action_id = (data.get("action_id") or "").strip()
        if not action_id:
            logger.warning("[bannerlord:%s] policy_result без action_id, skip", channel_id)
            return
        enacted = bool(data.get("enacted", True))
        new_status = "enacted" if enacted else "removed"

        from dependencies import get_db
        async with get_db()._connect() as conn:
            cur = await conn.execute(
                "UPDATE bannerlord_policy_requests SET status=? "
                "WHERE channel_id=? AND action_id=? AND status='pending'",
                (new_status, channel_id, action_id))
            await conn.commit()
            if cur.rowcount:
                logger.info("[bannerlord:%s] policy_result action_id=%s → %s",
                            channel_id, action_id, new_status)
            else:
                # Не ошибка: повторный эвент, или заявка от старого мода без
                # action_id в строке. Логируем, чтобы не искать молча.
                logger.info("[bannerlord:%s] policy_result action_id=%s — "
                            "нечего обновлять (повтор или заявка без action_id)",
                            channel_id, action_id)

    async def _on_action_failed(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Sprint 5.29 / BLT-parity #3 — refund крустиков на refuse мода.

        Mod handler refuse'ил action асинхронно (после ACK success=true в
        ActionPoller). Сейчас мод пушит action.failed event с action_id +
        reason. Backend ищет module_actions row, читает data.price, возвращает
        крустики в viewers.points, marks action error_msg = "REFUNDED:".

        Idempotent через error_msg LIKE 'REFUNDED:%' check.

        env.data: {action_id: str, reason: str}
        """
        action_id = (env.data or {}).get("action_id") or ""
        reason = (env.data or {}).get("reason") or "unspecified"
        if not action_id:
            logger.warning("[bannerlord:%s] action.failed без action_id, skip", channel_id)
            return

        # Sprint 5.32 BUGFIX — late-import get_db (как остальные methods в этом
        # файле). Раньше NameError: name 'get_db' is not defined ломал refund flow
        # → viewer'у не возвращались крустики на mod refuse.
        from dependencies import get_db
        async with get_db()._connect() as conn:
            try:
                await conn.execute("BEGIN IMMEDIATE")
                cur = await conn.execute(
                    "SELECT data, error_msg FROM module_actions "
                    "WHERE channel_id=? AND module_id='bannerlord' AND action_id=?",
                    (channel_id, action_id))
                row = await cur.fetchone()
                if not row:
                    await conn.execute("ROLLBACK")
                    logger.warning(
                        "[bannerlord:%s] action.failed action_id=%s not found",
                        channel_id, action_id)
                    return

                data_str, error_msg = row
                # Idempotent: уже refunded — skip
                if error_msg and error_msg.startswith("REFUNDED:"):
                    await conn.execute("ROLLBACK")
                    logger.info(
                        "[bannerlord:%s] action.failed action_id=%s already refunded, skip",
                        channel_id, action_id)
                    return

                # Parse data → price + initiated_by
                try:
                    import json as _json
                    parsed = _json.loads(data_str or "{}")
                except Exception:
                    parsed = {}
                price = int(parsed.get("price") or 0)
                username = (parsed.get("initiated_by") or "").lower()

                if price <= 0 or not username:
                    # Не было payment'а (free action) — лог + mark.
                    # 2026-07-28: статус тоже делаем терминальным. Иначе
                    # бесплатное действие после отказа остаётся 'queued',
                    # TTL-сторож будет натыкаться на него КАЖДЫЙ проход, а мод
                    # при перезапуске (курсор опроса сбрасывается в 0) увидит
                    # его снова и выполнит уже после отказа.
                    await conn.execute(
                        "UPDATE module_actions SET error_msg=?, status='failed' "
                        "WHERE channel_id=? AND module_id='bannerlord' AND action_id=?",
                        (f"REFUNDED:0 (no_price) reason={reason}", channel_id, action_id))
                    await self._drop_placeholder_rows(conn, channel_id, action_id)
                    await conn.commit()
                    logger.info(
                        "[bannerlord:%s] action.failed action_id=%s NO_REFUND "
                        "(price=%s user=%s reason=%s)",
                        channel_id, action_id, price, username, reason)
                    return

                # Refund крустики + ТЕРМИНАЛЬНЫЙ статус одной транзакцией.
                #
                # 2026-07-28 (T-02, внешний триаж 27.07). Раньше здесь менялся
                # только error_msg, а статус оставался 'queued'/'dispatched'.
                # Дальше приходил поздний `ACK success=true` — мод отвечает
                # РАНЬШЕ, чем работает, поэтому такой порядок штатен — и
                # `ack_action` (WHERE status IN ('queued','dispatched'))
                # перезаписывал error_msg в NULL, а статус в 'acked'.
                # Маркер `REFUNDED:` — единственная защита от повторного
                # возврата, и она стиралась: следующий action.failed платил
                # ВТОРОЙ раз. На проде 27.07 так вышло у четырёх действий.
                #
                # Теперь отказ сразу делает строку терминальной, и поздний ACK
                # становится no-op сам собой: его WHERE больше не совпадает.
                # Отдельно это закрывает S-10 (повторный ACK success=false
                # запускает синтетический возврат) — маркер доживает и гасит его.
                # Красный тест: tests/test_action_ack_refund_order.py
                await conn.execute(
                    "UPDATE viewers SET points = points + ? "
                    "WHERE channel_id=? AND username=?",
                    (price, channel_id, username))
                await conn.execute(
                    "UPDATE module_actions SET error_msg=?, status='failed' "
                    "WHERE channel_id=? AND module_id='bannerlord' AND action_id=?",
                    (f"REFUNDED:{price} reason={reason}", channel_id, action_id))
                await self._drop_placeholder_rows(conn, channel_id, action_id)
                await conn.commit()
                logger.info(
                    "[bannerlord:%s] REFUND ok action_id=%s user=%s +%s💎 reason=%s",
                    channel_id, action_id, username, price, reason)
            except Exception as ex:
                try:
                    await conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.exception(
                    "[bannerlord:%s] action.failed handler crashed action_id=%s: %s",
                    channel_id, action_id, ex)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def _on_session_start(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Session start handler.

        Чистим session-scoped catalogs (MULTITENANT_PLAN §H pattern).

        Sprint M22: save-switch detection. Сравниваем переданный save_id
        с last known для channel:
          • match → reload того же save, heroes persist
          • mismatch → стример загрузил другой save, heroes из старого
            не существуют в новом → DELETE all hero data для channel
            (zрители увидят "Стать героем" в extension)

        Mod передаёт save_id = Campaign.Current.UniqueGameId (boot-time
        stub "boot_*" для backwards-compat с старыми DLL).
        """
        save_id = env.data.get("save_id", "")
        from dependencies import get_db
        db = get_db()
        cleared = await db.clear_module_catalogs(channel_id, self.id)

        # M22: compare and reset on switch
        reset = False
        if save_id and not save_id.startswith("boot_"):
            async with db._connect() as conn:
                cur = await conn.execute(
                    "SELECT current_save_id FROM bannerlord_channel_state "
                    "WHERE channel_id=?", (channel_id,))
                row = await cur.fetchone()
                prev = (row[0] if row else None)
                if prev and prev != save_id:
                    # Save switched — другой playthrough → game-state из старого
                    # save больше не существует. 2026-06-01 FIX: раньше чистили
                    # ТОЛЬКО 5 hero-таблиц → fiefs/workshops/caravans/retinue/
                    # party_orders/heirs/auctions/… висели stale на новом сейве
                    # («Мои владения» показывали старые деревни). Теперь wipe тот
                    # же полный набор, что broadcaster-reset (RESETTABLE_TABLES) —
                    # single source of truth, списки больше не дрейфуют.
                    # Платформенные крустики (отдельная таблица) и system-каталоги
                    # (PRESERVED_TABLES) НЕ трогаются.
                    # 2026-06-05 (HERO-LOSS fix) — НЕ wipe'аем таблицы, которыми
                    # владеют snapshot-реконсайлеры: heroes_snapshot (hero-таблицы)
                    # и properties_snapshot (fief/workshop/caravan). Раньше blanket-
                    # wipe стирал ЖИВЫХ в игре героев на save-switch → extension
                    # показывал «Стать героем». Игра — источник правды: snapshot'ы
                    # сами удаляют то, чего нет в новом сейве, и (с ре-линком мода)
                    # пересоздают присутствующих. Чистим только НЕ-реконсайлимые
                    # per-save stale-таблицы (retinue/auctions/heirs/party_orders/…).
                    SNAPSHOT_OWNED = {
                        "bannerlord_heroes", "bannerlord_skills",
                        "bannerlord_attributes", "bannerlord_equipment",
                        "bannerlord_hero_class",
                        "bannerlord_fiefs", "bannerlord_workshops",
                        "bannerlord_caravans",
                    }
                    from routes.bannerlord_admin import RESETTABLE_TABLES
                    for table in RESETTABLE_TABLES:
                        if table == "bannerlord_channel_state":
                            continue  # управляется ниже через UPSERT
                        if table in SNAPSHOT_OWNED:
                            continue  # реконсайлится snapshot'ом — НЕ wipe'аем
                        # guard: таблица без колонки channel_id не роняет весь
                        # reset (sqlite3 OperationalError); логируем виновника.
                        try:
                            await conn.execute(
                                f"DELETE FROM {table} WHERE channel_id=?", (channel_id,))
                        except Exception as _wipe_ex:
                            print(f"[bannerlord:{channel_id}] session_start wipe "
                                  f"SKIP table '{table}': {_wipe_ex}")
                    reset = True
                # Update channel state regardless
                await conn.execute("""
                    INSERT INTO bannerlord_channel_state
                        (channel_id, current_save_id, last_session_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        current_save_id = excluded.current_save_id,
                        last_session_at = CURRENT_TIMESTAMP
                """, (channel_id, save_id))
                await conn.commit()

        print(f"[bannerlord:{channel_id}] session_start save_id={save_id} "
              f"(cleared {cleared} catalogs, stale_wipe={reset}, heroes/props PRESERVED)")

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
            # ON CONFLICT (channel_id, username) — re-adopt (после heir) обновляет hero_id.
            # Sprint 5.32 (BLT-parity H4) — также reset'им is_wounded=0 чтобы новый
            # hero не наследовал KO-флаг от мёртвого (m43 добавила колонку).
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
                    is_wounded   = 0,
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
        """Mod synced состояние hero (gold, location, alive/prisoner, +M19 meta)."""
        data = env.data
        username = (data.get("username") or "").lower()
        if not username:
            return

        # Sprint 5.29 BLT-parity #5: achievements high-water-mark tracking.
        # Push level/gold через set_stat_max — auto-detects new HWM.
        try:
            from routes.bannerlord_achievements import set_stat_max
            if "level" in data:
                await set_stat_max(channel_id, username, "level_max", int(data["level"] or 0))
            if "gold" in data:
                await set_stat_max(channel_id, username, "gold_max", int(data["gold"] or 0))
        except Exception:
            pass

        fields = []
        params: list = []
        # M19: level / clan_name / kingdom_name добавлены — mod пушит после
        # adoption + HeroLevelledUp + опционально на daily tick для clan/kingdom.
        # Sprint 5.32 (M43) — is_wounded для KO state (frontend показывает 🟡 ранен).
        for k in ("gold", "is_alive", "is_prisoner", "is_wounded", "location",
                  "level", "clan_name", "kingdom_name", "is_female"):
            if k in data:
                fields.append(f"{k} = ?")
                params.append(data[k])
        # 2026-06-10 — боевая стойка (валидируем — приходит от мода). Даёт
        # непустой fields даже для «голого» {username, combat_stance} апдейта.
        _stance = data.get("combat_stance")
        if _stance in ("defensive", "balanced", "aggressive"):
            fields.append("combat_stance = ?")
            params.append(_stance)
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

            # Sprint 5.8: UPSERT skills (level/focus) и attributes если пришли.
            skills_payload = data.get("skills")
            if isinstance(skills_payload, dict):
                for skill_key, info in skills_payload.items():
                    if not isinstance(info, dict):
                        continue
                    try:
                        level = int(info.get("level") or 0)
                        focus = int(info.get("focus") or 0)
                    except (TypeError, ValueError):
                        continue
                    await conn.execute("""
                        INSERT INTO bannerlord_skills
                            (channel_id, username, skill_key, level, xp, focus)
                        VALUES (?, ?, ?, ?, 0, ?)
                        ON CONFLICT(channel_id, username, skill_key) DO UPDATE SET
                            level = excluded.level,
                            focus = excluded.focus
                    """, (channel_id, username, skill_key, level, focus))

            attrs_payload = data.get("attributes")
            if isinstance(attrs_payload, dict):
                for attr_key, value in attrs_payload.items():
                    try:
                        v = int(value)
                    except (TypeError, ValueError):
                        continue
                    await conn.execute("""
                        INSERT INTO bannerlord_attributes
                            (channel_id, username, attribute, value)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(channel_id, username, attribute) DO UPDATE SET
                            value = excluded.value
                    """, (channel_id, username, attr_key, v))

            # Sprint 5.11+5.27c: clan_info / kingdom_info / family_info JSON storage
            for k, col in [("clan_info", "clan_info_json"),
                           ("kingdom_info", "kingdom_info_json"),
                           ("family_info", "family_info_json"),
                           ("party_info", "party_info_json")]:
                info = data.get(k)
                if info is not None:
                    try:
                        json_str = json.dumps(info, ensure_ascii=False) if info else None
                    except Exception:
                        json_str = None
                    await conn.execute(
                        f"UPDATE bannerlord_heroes SET {col}=? "
                        f"WHERE channel_id=? AND username=?",
                        (json_str, channel_id, username))

            await conn.commit()

    async def _on_player_died(self, channel_id: int, env: ModuleEnvelope) -> None:
        """HeroKilled event. Mark dead + bump iteration counter for heir succession.

        Sprint 5.29 / BLT-parity #7: instead of auto-respawn, mark dead и
        increment iteration. Frontend show'ает «Поколение N мёртв + Возродить»
        button. Viewer click'ает → POST hero.create → AdoptHeroHandler берёт
        new wanderer with same username (iteration N+1).

        Old hero остаётся в game world как dead [BLink] @username (engine не
        re-spawn'ит мёртвых), новый — fresh start от 0 уровня.
        """
        data = env.data
        username = (data.get("username") or "").lower()
        if not username:
            return

        from dependencies import get_db
        import uuid as _uuid
        async with get_db()._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET is_alive=0, "
                "iteration = iteration + 1, "
                "last_sync=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))

            # Sprint 5.32 (BLT-parity M2.1) — heir auto-activation.
            # Pick first alive non-activated heir → mark activated=1 → enqueue
            # mod action hero.activate_heir с heir_hero_id + parent_username.
            # Mod renames heir → [BLink] {parent_username}, transfers clan,
            # пушит player.linked. Viewer мгновенно получает нового hero без
            # клика "Возродить" + без потери прогресса (heir уже level'нутый
            # ребёнок with parent's clan/skills).
            #
            # Fallback: если heirs нет — existing flow ("Поколение N мёртв,
            # возродить" UI button → AdoptHeroHandler new wanderer).
            cur_heir = await conn.execute(
                "SELECT heir_hero_id, heir_name FROM bannerlord_heirs "
                "WHERE channel_id=? AND parent_username=? "
                "AND alive=1 AND activated=0 "
                "ORDER BY came_of_age_at ASC LIMIT 1",  # старший first (came_of_age earliest)
                (channel_id, username))
            heir_row = await cur_heir.fetchone()
            heir_activated = None
            inherited_count = 0
            if heir_row:
                heir_id, heir_name = heir_row
                # Mark activated to prevent picking same heir on second death.
                await conn.execute(
                    "UPDATE bannerlord_heirs SET activated=1 "
                    "WHERE channel_id=? AND heir_hero_id=?",
                    (channel_id, heir_id))

                # Sprint 5.33 (BLT-parity HERITAGE) — collect parent's assets,
                # pass payload to mod handler для engine-side ownership transfer.
                # Backend rows already keyed by owner_username (unchanged через
                # heir rename), но engine ownership уходит к notable on death →
                # mod ApplyByDeath default behavior. HERITAGE re-claims это.
                inherited_workshops = []
                inherited_caravans = []
                inherited_fiefs = []
                try:
                    cur_w = await conn.execute(
                        "SELECT id, settlement_id, settlement_name, workshop_type, "
                        "       workshop_type_name, total_profit "
                        "FROM bannerlord_workshops "
                        "WHERE channel_id=? AND owner_username=? AND status='active'",
                        (channel_id, username))
                    for r in await cur_w.fetchall():
                        inherited_workshops.append({
                            "row_id":            r[0],
                            "settlement_id":     r[1],
                            "settlement_name":   r[2],
                            "workshop_type":     r[3],
                            "workshop_type_name": r[4],
                            "total_value":       r[5] or 0,
                        })

                    cur_c = await conn.execute(
                        "SELECT id, party_id, home_settlement_name, total_collected_dinars "
                        "FROM bannerlord_caravans "
                        "WHERE channel_id=? AND owner_username=? AND status='active' "
                        "  AND party_id IS NOT NULL",
                        (channel_id, username))
                    for r in await cur_c.fetchall():
                        inherited_caravans.append({
                            "row_id":            r[0],
                            "party_id":          r[1],
                            "home_name":         r[2],
                            "total_value":       r[3] or 0,
                        })

                    cur_f = await conn.execute(
                        "SELECT id, fief_id, fief_name, fief_type, total_collected_dinars "
                        "FROM bannerlord_fiefs "
                        "WHERE channel_id=? AND owner_username=?",
                        (channel_id, username))
                    for r in await cur_f.fetchall():
                        inherited_fiefs.append({
                            "row_id":         r[0],
                            "fief_id":        r[1],
                            "fief_name":      r[2],
                            "fief_type":      r[3],
                            "total_value":    r[4] or 0,
                        })
                except Exception as ex_assets:
                    logger.warning("[HERITAGE] asset collection warn ch=%s @%s: %s",
                                   channel_id, username, ex_assets)

                # Log inheritance entries (audit, frontend "Наследие" section).
                import json as _json_h
                for w in inherited_workshops:
                    await conn.execute(
                        "INSERT INTO bannerlord_inheritance_log "
                        "(channel_id, parent_username, heir_hero_id, "
                        " asset_type, asset_ref, asset_name, total_value) "
                        "VALUES (?, ?, ?, 'workshop', ?, ?, ?)",
                        (channel_id, username, heir_id,
                         _json_h.dumps({"settlement_id": w["settlement_id"],
                                        "workshop_type": w["workshop_type"]}),
                         f"{w.get('workshop_type_name') or '?'} в {w.get('settlement_name') or '?'}",
                         w["total_value"]))
                    inherited_count += 1
                for c in inherited_caravans:
                    await conn.execute(
                        "INSERT INTO bannerlord_inheritance_log "
                        "(channel_id, parent_username, heir_hero_id, "
                        " asset_type, asset_ref, asset_name, total_value) "
                        "VALUES (?, ?, ?, 'caravan', ?, ?, ?)",
                        (channel_id, username, heir_id,
                         _json_h.dumps({"party_id": c["party_id"]}),
                         f"Караван из {c.get('home_name') or '?'}",
                         c["total_value"]))
                    inherited_count += 1
                for f in inherited_fiefs:
                    await conn.execute(
                        "INSERT INTO bannerlord_inheritance_log "
                        "(channel_id, parent_username, heir_hero_id, "
                        " asset_type, asset_ref, asset_name, total_value) "
                        "VALUES (?, ?, ?, 'fief', ?, ?, ?)",
                        (channel_id, username, heir_id,
                         _json_h.dumps({"fief_id": f["fief_id"],
                                        "fief_type": f["fief_type"]}),
                         f"{f.get('fief_type') or '?'}: {f.get('fief_name') or '?'}",
                         f["total_value"]))
                    inherited_count += 1

                # Enqueue mod action — extended payload с inherited_assets.
                action_id = _uuid.uuid4().hex
                payload = {
                    "initiated_by":    username,
                    "target":          username,
                    "parent_username": username,
                    "heir_hero_id":    heir_id,
                    "heir_name":       heir_name,
                    "_auto":           True,
                    # HERITAGE: assets — mod re-transfers engine ownership.
                    "inherited_workshops": inherited_workshops,
                    "inherited_caravans":  inherited_caravans,
                    "inherited_fiefs":     inherited_fiefs,
                }
                import json as _json
                await conn.execute("""
                    INSERT INTO module_actions
                        (channel_id, module_id, action_id, type, data, status)
                    VALUES (?, 'bannerlord', ?, 'hero.activate_heir', ?, 'queued')
                """, (channel_id, action_id,
                      _json.dumps(payload, ensure_ascii=False)))
                heir_activated = (heir_id, heir_name)

            await conn.commit()

        await self._log_event(channel_id, "player.died", username, data)
        if heir_activated:
            # Sprint 5.32 (LOG-3) — explicit prefix для heir-activation flow.
            heritage_suffix = (f" + HERITAGE: {inherited_count} assets passed"
                               if inherited_count > 0 else "")
            print(f"[HEIR-ACTIVATE] ch={channel_id} @{username} died → "
                  f"AUTO-HEIR queued: '{heir_activated[1]}' (id={heir_activated[0]}) "
                  f"— mod должен ActivateHeirHandler execute через ~1s"
                  f"{heritage_suffix}")
        else:
            print(f"[HEIR-ACTIVATE] ch={channel_id} @{username} died, "
                  f"NO HEIR (iteration bumped to next) "
                  f"killer={data.get('killer_name', 'unknown')}")

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
        """Hero equipped/unequipped item.

        M21: payload расширен — tier / item_value / weight / stats (per-type
        dict). stats хранится как JSON string в bannerlord_equipment.stats_json.
        Старые events (без stats) тоже supported — поля nullable.
        """
        data = env.data
        username = (data.get("username") or "").lower()
        slot = (data.get("slot") or "").lower()
        item_id = data.get("item_id")  # None = unequipped
        item_name = data.get("item_name")
        if not username or not slot:
            return

        # M21 extended fields
        tier = data.get("tier")              # int 0-5 or None
        item_value = data.get("item_value")  # int or None
        weight = data.get("weight")          # float or None
        stats = data.get("stats")            # dict or None
        stats_json = json.dumps(stats, ensure_ascii=False) if stats is not None else None
        # M77 (2026-06-15 «Кузница»): качество ItemModifier'а — poor/inferior/
        # common/fine/masterwork/legendary, либо None (без модификатора).
        quality = data.get("quality")        # str or None

        from dependencies import get_db
        async with get_db()._connect() as conn:
            if item_id:
                await conn.execute("""
                    INSERT INTO bannerlord_equipment
                        (channel_id, username, slot, item_id, item_name,
                         tier, item_value, weight, stats_json, quality)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(channel_id, username, slot) DO UPDATE SET
                        item_id    = excluded.item_id,
                        item_name  = excluded.item_name,
                        tier       = excluded.tier,
                        item_value = excluded.item_value,
                        weight     = excluded.weight,
                        stats_json = excluded.stats_json,
                        quality    = excluded.quality
                """, (channel_id, username, slot, item_id, item_name,
                      tier, item_value, weight, stats_json, quality))
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

    async def _on_heroes_snapshot(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит при OnSessionLaunched список ВСЕХ alive heroes (lowercase
        names) в текущем save. Backend diff'ит с bannerlord_heroes для канала
        и DELETE'ит rows которых нет в snapshot — extension покажет
        "Стать героем" для viewer'ов чей hero отсутствует в новом save.

        Корректно работает между save файлами одной campaign (где UniqueGameId
        совпадает, но AliveHeroes может различаться если ты убил/удалил heroes).
        Per-hero existence check вместо save_id matching.
        """
        data = env.data
        # 2026-06-05 (SELF-HEAL) — игра = источник правды по героям. Новый мод
        # шлёт rich `heroes` [{username, hero_id, display_name, culture}] →
        # backend UPSERT'ит присутствующих (ПЕРЕСОЗДаёт hero-строки, потерянные
        # из-за save-switch wipe / порчи БД) + удаляет отсутствующих. Старый DLL
        # шлёт только `usernames` → fallback delete-only (backward-compat).
        rich: dict = {}
        heroes_payload = data.get("heroes")
        if isinstance(heroes_payload, list):
            for h in heroes_payload:
                if not isinstance(h, dict):
                    continue
                u = str(h.get("username") or "").lower()
                if u:
                    rich[u] = h
        if rich:
            snapshot = set(rich.keys())
        else:
            usernames = data.get("usernames") or []
            if not isinstance(usernames, list):
                return
            snapshot = {str(u).lower() for u in usernames if u}

        from dependencies import get_db
        upserted = 0
        async with get_db()._connect() as conn:
            # 1. UPSERT присутствующих — пересоздаёт пропавшие hero-строки.
            #    is_alive=1 на create; на conflict трогаем ТОЛЬКО identity-поля
            #    (gold/level/clan/is_wounded оставляем _on_player_state_update).
            for u, h in rich.items():
                hero_id = h.get("hero_id") or ""
                if not hero_id:
                    continue
                await conn.execute("""
                    INSERT INTO bannerlord_heroes
                        (channel_id, username, hero_id, display_name, culture, is_alive)
                    VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(channel_id, username) DO UPDATE SET
                        hero_id      = excluded.hero_id,
                        display_name = excluded.display_name,
                        culture      = COALESCE(excluded.culture, culture)
                """, (channel_id, u, hero_id,
                      h.get("display_name") or u, h.get("culture")))
                upserted += 1

            # 2. DELETE отсутствующих (есть в БД, но не в snapshot текущего сейва).
            cur = await conn.execute(
                "SELECT username FROM bannerlord_heroes WHERE channel_id=?",
                (channel_id,))
            existing = [row[0] for row in await cur.fetchall()]
            missing = [u for u in existing if u not in snapshot]
            if missing:
                placeholders = ",".join("?" * len(missing))
                for table in ("bannerlord_heroes", "bannerlord_skills",
                              "bannerlord_attributes", "bannerlord_equipment",
                              "bannerlord_hero_class"):
                    await conn.execute(
                        f"DELETE FROM {table} WHERE channel_id=? AND username IN ({placeholders})",
                        [channel_id] + missing)
                # герой пропал из save → его passive-income game-state тоже больше
                # не существует (column owner_username): fief/workshop/caravan.
                for table in ("bannerlord_fiefs", "bannerlord_workshops",
                              "bannerlord_caravans"):
                    await conn.execute(
                        f"DELETE FROM {table} WHERE channel_id=? AND owner_username IN ({placeholders})",
                        [channel_id] + missing)
            await conn.commit()

        print(f"[bannerlord:{channel_id}] heroes_snapshot: "
              f"{len(snapshot)} alive in save, upserted {upserted}, "
              f"removed {len(missing)} stale ({missing[:3]}...)")

    async def _on_properties_snapshot(self, channel_id: int, env: ModuleEnvelope) -> None:
        """2026-06-02 (PROPERTIES-MIRROR) — игра = источник правды по владениям.

        Mod пушит (на коннекте + раз в game-day) ПОЛНЫЙ список fiefs/workshops/
        caravans, которыми [BLink]-герои владеют СЕЙЧАС. Backend зеркалит каждую
        категорию: upsert присутствующих (сохраняя накопит. статистику —
        total_collected_dinars / total_profit / opened_at) + DELETE отсутствующих.

        Лечит "призраков": проданный/потерянный/уничтоженный фьеф/мастерская/
        караван больше не висит в «Мои владения». Обобщает _on_heroes_snapshot
        (тот чистил по owner'у ПРОПАВШЕГО героя; этот — по game-id самой сущности,
        ловит «герой жив, но продал/потерял конкретный караван/фьеф»).
        """
        data = env.data
        fiefs = data.get("fiefs") or []
        workshops = data.get("workshops") or []
        caravans = data.get("caravans") or []

        from routes.bannerlord_fiefs import reconcile_fiefs
        from routes.bannerlord_workshops import reconcile_workshops
        from routes.bannerlord_caravans import reconcile_caravans
        from dependencies import get_db
        async with get_db()._connect() as conn:
            nf = await reconcile_fiefs(conn, channel_id, fiefs)
            nw = await reconcile_workshops(conn, channel_id, workshops)
            nc = await reconcile_caravans(conn, channel_id, caravans)
            await conn.commit()

        print(f"[bannerlord:{channel_id}] properties_snapshot mirror: "
              f"fiefs n={nf['n']} -{nf['removed']}, "
              f"workshops n={nw['n']} -{nw['removed']}, "
              f"caravans n={nc['n']} -{nc['removed']}")

    async def _on_retinue_changed(self, channel_id: int, env: ModuleEnvelope) -> None:
        """M23: mod после recruit/upgrade troop пушит обновлённый slot.

        Payload: {username, slot_index, troop_id, troop_name, tier, action}
        Backend UPSERT'ит row в bannerlord_retinue.
        """
        data = env.data
        username = (data.get("username") or "").lower()
        try:
            slot_index = int(data.get("slot_index"))
        except (TypeError, ValueError):
            return
        troop_id = data.get("troop_id") or ""
        troop_name = data.get("troop_name") or troop_id
        try:
            tier = int(data.get("tier") or 0)
        except (TypeError, ValueError):
            tier = 0
        is_elite = 1 if bool(data.get("is_elite", False)) else 0
        if not username or not troop_id:
            return

        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute("""
                INSERT INTO bannerlord_retinue
                    (channel_id, username, slot_index, troop_id, troop_name, tier, is_elite)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id, username, slot_index) DO UPDATE SET
                    troop_id   = excluded.troop_id,
                    troop_name = excluded.troop_name,
                    tier       = excluded.tier,
                    is_elite   = excluded.is_elite
            """, (channel_id, username, slot_index, troop_id, troop_name, tier, is_elite))
            await conn.commit()
        action = data.get("action", "?")
        print(f"[bannerlord:{channel_id}] @{username} retinue {action}: "
              f"slot {slot_index} → {troop_id} T{tier + 1} "
              f"{'[ELITE]' if is_elite else ''}")

    async def _on_retinue_casualty(self, channel_id: int, env: ModuleEnvelope) -> None:
        """2026-05-29 (BLT RetinueDeathChance): войско свиты погибло в бою НАВСЕГДА.

        Payload: {username, troop_id, troop_name}
        Удаляем ОДИН слот (минимальный slot_index) с этим troop_id и
        re-pack'им оставшиеся slot_index'ы в непрерывный 0..N-1 — иначе recruit
        (slot = existing.Count) затрёт существующий слот при заполнении дыры.
        """
        data = env.data
        username = (data.get("username") or "").lower()
        troop_id = data.get("troop_id") or ""
        if not username or not troop_id:
            return

        from dependencies import get_db
        async with get_db()._connect() as conn:
            cur = await conn.execute(
                "SELECT slot_index FROM bannerlord_retinue "
                "WHERE channel_id=? AND username=? AND troop_id=? "
                "ORDER BY slot_index LIMIT 1",
                (channel_id, username, troop_id))
            row = await cur.fetchone()
            if not row:
                return
            dead_slot = row[0]

            # Удаляем погибший слот, затем re-pack оставшихся.
            await conn.execute(
                "DELETE FROM bannerlord_retinue "
                "WHERE channel_id=? AND username=? AND slot_index=?",
                (channel_id, username, dead_slot))

            cur = await conn.execute(
                "SELECT troop_id, troop_name, tier, COALESCE(is_elite, 0) "
                "FROM bannerlord_retinue "
                "WHERE channel_id=? AND username=? ORDER BY slot_index",
                (channel_id, username))
            remaining = await cur.fetchall()
            await conn.execute(
                "DELETE FROM bannerlord_retinue WHERE channel_id=? AND username=?",
                (channel_id, username))
            for new_idx, r in enumerate(remaining):
                await conn.execute(
                    "INSERT INTO bannerlord_retinue "
                    "(channel_id, username, slot_index, troop_id, troop_name, tier, is_elite) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (channel_id, username, new_idx, r[0], r[1], r[2], r[3]))
            await conn.commit()

        troop_name = data.get("troop_name") or troop_id
        print(f"[bannerlord:{channel_id}] @{username} retinue CASUALTY: "
              f"{troop_name} ({troop_id}) погиб навсегда — slot {dead_slot} "
              f"удалён, осталось {len(remaining)}")

    async def _on_gear_tier_changed(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod применил gear upgrade — backend сохраняет new tier в DB cache.

        Mod source-of-truth: tier обновляется ТОЛЬКО после successful in-game
        upgrade (Hero.Gold deducted, equipment replaced). Backend не управляет
        tier'ом сам; этот event = ack от mod'а.
        """
        data = env.data
        username = (data.get("username") or "").lower()
        new_tier = int(data.get("gear_tier") or 0)
        if not username or new_tier < 1 or new_tier > 6:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET gear_tier=?, last_sync=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND username=?",
                (new_tier, channel_id, username))
            await conn.commit()
        await self._log_event(channel_id, "hero.gear_tier_changed", username, data)
        print(f"[bannerlord:{channel_id}] @{username} gear_tier → T{new_tier}")

    async def _on_restore_profile(self, channel_id: int, env: ModuleEnvelope) -> None:
        """2026-06-15 — мод восстанавливает per-save backend-only стейт героя при
        ЗАГРУЗКЕ сейва (class_key / combat_stance / gear_tier / retinue — из SyncData
        сейва). Перезаписывает backend, чтобы фронт показывал класс/стойку/тир/свиту
        ИМЕННО загруженного сейва, а не другого playthrough на этом канале. Поля
        опциональны — пишем присутствующие.
        """
        data = env.data or {}
        username = (data.get("username") or "").lower()
        if not username:
            return
        class_key = data.get("class_key")
        stance = data.get("stance")
        gear_tier = data.get("gear_tier")
        retinue = data.get("retinue")
        from dependencies import get_db
        async with get_db()._connect() as conn:
            # class — UPSERT (class_level не трогаем; FK на bannerlord_classes —
            # на всякий случай в try, чтобы битый class_key не ронял весь restore).
            if class_key:
                try:
                    await conn.execute("""
                        INSERT INTO bannerlord_hero_class (channel_id, username, class_key, class_level)
                        VALUES (?, ?, ?, 1)
                        ON CONFLICT(channel_id, username) DO UPDATE SET class_key=excluded.class_key
                    """, (channel_id, username, class_key))
                except Exception as _ex:
                    print(f"[bannerlord:{channel_id}] restore_profile class skip @{username}: {_ex}")
            # stance + gear_tier — колонки bannerlord_heroes.
            sets, params = [], []
            if stance in ("defensive", "balanced", "aggressive"):
                sets.append("combat_stance = ?")
                params.append(stance)
            if isinstance(gear_tier, int) and 0 <= gear_tier <= 6:
                sets.append("gear_tier = ?")
                params.append(gear_tier)
            if sets:
                params += [channel_id, username]
                await conn.execute(
                    f"UPDATE bannerlord_heroes SET {', '.join(sets)}, last_sync=CURRENT_TIMESTAMP "
                    f"WHERE channel_id=? AND username=?", params)
            # retinue — полный список из сейва → пересобираем bannerlord_retinue
            # (на смене сейва таблица wipe'нута session_start'ом; здесь восстанавливаем
            # свиту ИМЕННО этого сейва). Только если список реально пришёл.
            n_ret = -1
            if isinstance(retinue, list):
                await conn.execute(
                    "DELETE FROM bannerlord_retinue WHERE channel_id=? AND username=?",
                    (channel_id, username))
                n_ret = 0
                for slot in retinue:
                    if not isinstance(slot, dict):
                        continue
                    try:
                        await conn.execute("""
                            INSERT INTO bannerlord_retinue
                                (channel_id, username, slot_index, troop_id, troop_name, tier, is_elite)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (channel_id, username, slot.get("slot_index"),
                              slot.get("troop_id"), slot.get("troop_name"),
                              slot.get("tier"), 1 if slot.get("is_elite") else 0))
                        n_ret += 1
                    except Exception as _ex:
                        print(f"[bannerlord:{channel_id}] restore_profile retinue slot skip @{username}: {_ex}")
            await conn.commit()
        print(f"[bannerlord:{channel_id}] @{username} profile restored "
              f"(class={class_key}, stance={stance}, gear_tier={gear_tier}, retinue={n_ret})")

    async def _on_restore_clan_upgrades(self, channel_id: int, env: ModuleEnvelope) -> None:
        """2026-06-15 — мод на загрузке сейва восстанавливает owned clan-upgrades
        ЭТОГО сейва (из SyncData) после вайпа. MERGE через INSERT OR IGNORE — НЕ
        удаляет более новые покупки (на смене сейва бэк уже пуст после вайпа; на
        reload того же сейва — no-op). env.data: {owned: {username: [upgrade_id]}}.
        gold_paid восстановить неоткуда → 0 (это только accounting; эффект тика
        зависит только от upgrade_id)."""
        data = env.data or {}
        owned = data.get("owned") or {}
        if not isinstance(owned, dict) or not owned:
            return
        from dependencies import get_db
        n = 0
        async with get_db()._connect() as conn:
            for username, ids in owned.items():
                uname = (username or "").lower()
                if not uname or not isinstance(ids, list):
                    continue
                for uid in ids:
                    if not uid:
                        continue
                    try:
                        await conn.execute(
                            "INSERT OR IGNORE INTO bannerlord_clan_upgrades_owned "
                            "(channel_id, username, upgrade_id, gold_paid) VALUES (?, ?, ?, 0)",
                            (channel_id, uname, str(uid)))
                        n += 1
                    except Exception as _ex:
                        print(f"[bannerlord:{channel_id}] restore_clan_upgrades skip @{uname}/{uid}: {_ex}")
            await conn.commit()
        print(f"[bannerlord:{channel_id}] clan_upgrades restored: {n} row(s), {len(owned)} owner(s)")

    # ── Sprint 5.8: Focus / Attribute changes ─────────────────────────────────

    async def _on_focus_changed(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит после successful add_focus. Backend log'ает в audit
        (UI отображение позже — для MVP только log)."""
        data = env.data or {}
        username = (data.get("username") or "").lower()
        skill = data.get("skill_name") or data.get("skill_key") or "?"
        new_focus = data.get("new_focus")
        cost = data.get("cost") or 0
        await self._log_event(channel_id, "hero.focus_changed", username, data)
        print(f"[bannerlord:{channel_id}] @{username} focus +{data.get('amount', 1)} "
              f"в {skill} → F{new_focus} (-{cost}💰)")

    async def _on_attribute_changed(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит после successful add_attribute. UPSERT в bannerlord_attributes
        (existing M14 table) для UI display."""
        data = env.data or {}
        username = (data.get("username") or "").lower()
        attr_key = data.get("attribute_key") or "?"
        new_val = data.get("new_value") or 0
        cost = data.get("cost") or 0
        if not username or not attr_key or attr_key == "?":
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute("""
                INSERT INTO bannerlord_attributes
                    (channel_id, username, attribute, value)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_id, username, attribute) DO UPDATE SET
                    value = excluded.value
            """, (channel_id, username, attr_key, new_val))
            await conn.commit()
        await self._log_event(channel_id, "hero.attribute_changed", username, data)
        print(f"[bannerlord:{channel_id}] @{username} attribute +{data.get('amount', 1)} "
              f"в {attr_key} → {new_val} (-{cost}💰)")

    # ── Sprint 5.9: Clan creation ─────────────────────────────────────────────

    async def _on_clan_created(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит после успешного hero.create_clan. UPDATE bannerlord_heroes
        с новым clan_name (UI отображение)."""
        data = env.data or {}
        username = (data.get("username") or "").lower()
        clan_name = data.get("clan_name") or ""
        if not username or not clan_name:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET clan_name=?, last_sync=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND username=?",
                (clan_name, channel_id, username))
            await conn.commit()
        await self._log_event(channel_id, "hero.clan_created", username, data)
        # Sprint 5.29 BLT-parity #5: achievement trigger
        try:
            from routes.bannerlord_achievements import set_stat_flag
            await set_stat_flag(channel_id, username, "clan_created")
        except Exception:
            pass
        print(f"[bannerlord:{channel_id}] @{username} created clan '{clan_name}' "
              f"(culture={data.get('culture')}, home={data.get('home_settlement')})")

    # ── Sprint 5.29 audit fix #33: 6 manifest events для clan/kingdom/party ──
    # Раньше mod пушил эти events → backend logged "unhandled" → bannerlord_heroes
    # cache stale (clan_name/kingdom_name не обновлялся до следующего полного
    # player.state_update push'а от мода, что могло быть через минуты). UI показывал
    # старое значение → viewer думал что action не сработал.

    async def _on_clan_joined(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит после hero.join_clan. UPDATE clan_name."""
        data = env.data or {}
        username = (data.get("username") or "").lower()
        clan_name = data.get("clan_name") or ""
        if not username or not clan_name:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET clan_name=?, last_sync=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND username=?",
                (clan_name, channel_id, username))
            await conn.commit()
        await self._log_event(channel_id, "hero.clan_joined", username, data)
        logger.info("[bannerlord:%s] @%s joined clan '%s'", channel_id, username, clan_name)

    async def _on_clan_left(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит после hero.leave_clan. UPDATE clan_name=NULL (и kingdom_name=NULL
        потому что покидание clan'а косвенно отвязывает от kingdom)."""
        data = env.data or {}
        username = (data.get("username") or "").lower()
        if not username:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET clan_name=NULL, kingdom_name=NULL, "
                "last_sync=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))
            await conn.commit()
        await self._log_event(channel_id, "hero.clan_left", username, data)
        logger.info("[bannerlord:%s] @%s left clan (was '%s')",
                    channel_id, username, data.get("old_clan_name") or "?")

    async def _on_kingdom_created(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит после hero.create_kingdom. UPDATE kingdom_name."""
        data = env.data or {}
        username = (data.get("username") or "").lower()
        kingdom_name = data.get("kingdom_name") or ""
        if not username or not kingdom_name:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET kingdom_name=?, last_sync=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND username=?",
                (kingdom_name, channel_id, username))
            await conn.commit()
        await self._log_event(channel_id, "hero.kingdom_created", username, data)
        # Sprint 5.29 BLT-parity #5: achievement trigger
        try:
            from routes.bannerlord_achievements import set_stat_flag
            await set_stat_flag(channel_id, username, "kingdom_created")
        except Exception:
            pass
        logger.info("[bannerlord:%s] @%s created kingdom '%s'",
                    channel_id, username, kingdom_name)

    async def _on_kingdom_joined(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит после hero.join_kingdom. UPDATE kingdom_name."""
        data = env.data or {}
        username = (data.get("username") or "").lower()
        kingdom_name = data.get("kingdom_name") or ""
        if not username or not kingdom_name:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET kingdom_name=?, last_sync=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND username=?",
                (kingdom_name, channel_id, username))
            await conn.commit()
        await self._log_event(channel_id, "hero.kingdom_joined", username, data)
        logger.info("[bannerlord:%s] @%s joined kingdom '%s'",
                    channel_id, username, kingdom_name)

    async def _on_kingdom_left(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит после hero.leave_kingdom (clan покидает kingdom).
        UPDATE kingdom_name=NULL."""
        data = env.data or {}
        username = (data.get("username") or "").lower()
        if not username:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET kingdom_name=NULL, "
                "last_sync=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))
            await conn.commit()
        await self._log_event(channel_id, "hero.kingdom_left", username, data)
        logger.info("[bannerlord:%s] @%s left kingdom (was '%s')",
                    channel_id, username, data.get("old_kingdom_name") or "?")

    async def _on_party_created(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит после hero.create_party. Логируем (sample data в audit log).
        bannerlord_heroes не имеет party_name column'а — только лог."""
        data = env.data or {}
        username = (data.get("username") or "").lower()
        if not username:
            return
        await self._log_event(channel_id, "hero.party_created", username, data)
        logger.info("[bannerlord:%s] @%s created party '%s' at '%s'",
                    channel_id, username,
                    data.get("party_name") or "?",
                    data.get("spawn_settlement") or "?")

    # ── Sprint 5.4: Battle stats snapshot ─────────────────────────────────────

    def _on_battle_stats(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod push'нул snapshot участников Mission. Сохраняем в memory
        для overlay polling + viewer-side battle banner.

        Sprint 5.5: detect новый бой → reset cooldowns participating viewers.
        Условия "новый бой":
          • не было предыдущего snapshot'а ИЛИ
          • предыдущий был final=True ИЛИ
          • прошло > BATTLE_STATS_TTL с прошлого push'а (stale)
        """
        import time as _time
        data = env.data or {}
        participants = data.get("participants") or []
        if not isinstance(participants, list):
            participants = []
        is_final = bool(data.get("final"))
        now = _time.time()

        # Detect new battle transition
        prev = _battle_stats.get(channel_id)
        is_new_battle = False
        if not is_final and len(participants) > 0:
            if not prev:
                is_new_battle = True
            elif prev.get("final"):
                is_new_battle = True
            elif now - prev.get("updated_at", 0) > _BATTLE_STATS_TTL:
                is_new_battle = True

        # Sprint 5.29 BLT-parity #5: kills achievement — fire-and-forget
        # incremental delta. Battle.stats_snapshot имеет cumulative kills
        # per username — track previous, increment delta. Only при is_final
        # чтобы избежать race на short snapshot intervals + дешевле DB writes.
        # 2026-07-21 — ПОЧИНЕНО. Было: delta = финал − ПРЕДЫДУЩИЙ снапшот, и только
        # если prev вообще есть. Но `kills` в снапшоте кумулятивны В ПРЕДЕЛАХ БОЯ, а
        # инкремент пишется только на финале → засчитывался лишь последний интервал
        # (обычно 0-1), всё набитое раньше терялось; короткие бои с единственным
        # снапшотом (prev=None) не считались вовсе. Результат: за всё время в БД
        # 1 килл на 26 игроков → ачивки 100/500/1000 недостижимы, и измерить баланс
        # классов нечем. Теперь на финале засчитываем ВЕСЬ бой целиком.
        if is_final:
            try:
                import asyncio as _asyncio
                from routes.bannerlord_achievements import increment_stat as _inc
                async def _ach_kills_apply():
                    for p in participants:
                        u = (p.get("username") or "").lower()
                        if not u:
                            continue
                        battle_kills = int(p.get("kills") or 0)
                        if battle_kills > 0:
                            try:
                                await _inc(channel_id, u, "kills", battle_kills)
                            except Exception:
                                pass
                _asyncio.create_task(_ach_kills_apply())
            except Exception:
                pass

        _battle_stats[channel_id] = {
            "final":        is_final,
            "updated_at":   now,
            "participants": participants,
        }

        # New battle → reset active cooldowns participating viewers
        # (heal_burst / shield_break / rage / retribution / player.spawn).
        if is_new_battle:
            cleared = 0
            for p in participants:
                u = (p.get("username") or "").lower()
                if not u:
                    continue
                key = (channel_id, u)
                if key in _cooldowns:
                    del _cooldowns[key]
                    cleared += 1
            if cleared > 0:
                print(f"[bannerlord:{channel_id}] new battle started — "
                      f"reset cooldowns for {cleared} participant(s)")

        # Log только final (snapshot spam)
        if is_final:
            kills_total = sum(int(p.get("kills") or 0) for p in participants)
            print(f"[bannerlord:{channel_id}] battle.stats final — "
                  f"{len(participants)} heroes, {kills_total} kills total")

    # ── Sprint 5.3: Tournament events ─────────────────────────────────────────

    async def _on_tournament_joined(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod после deduct Hero.Gold добавил viewer'а в TournamentQueue —
        backend INSERT'ит row для UI mirror.

        Payload: {username, entry_fee}
        """
        data = env.data
        username = (data.get("username") or "").lower()
        try:
            entry_fee = int(data.get("entry_fee") or 0)
        except (TypeError, ValueError):
            entry_fee = 0
        if not username:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute("""
                INSERT INTO bannerlord_tournament_queue
                    (channel_id, username, entry_fee)
                VALUES (?, ?, ?)
                ON CONFLICT(channel_id, username) DO UPDATE SET
                    entry_fee = excluded.entry_fee,
                    joined_at = CURRENT_TIMESTAMP
            """, (channel_id, username, entry_fee))
            await conn.commit()
        print(f"[bannerlord:{channel_id}] @{username} joined tournament "
              f"queue (fee={entry_fee}💰)")

    async def _on_tournament_left(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Viewer убран из очереди (hero died между join и start, refund etc.)."""
        data = env.data
        username = (data.get("username") or "").lower()
        if not username:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "DELETE FROM bannerlord_tournament_queue "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))
            await conn.commit()
        print(f"[bannerlord:{channel_id}] @{username} left tournament queue")

    async def _on_tournament_started(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Турнир начался — backend сохраняет participants snapshot.

        Payload: {participants: [username...]}
        Очередь очищается; этот же list используется для bet validation
        и для финального payout.
        """
        data = env.data
        participants = data.get("participants") or []
        if not isinstance(participants, list):
            participants = []
        participants = [str(p).lower() for p in participants]
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute("""
                INSERT INTO bannerlord_tournament_state
                    (channel_id, status, current_round, participants, started_at)
                VALUES (?, 'running', 0, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(channel_id) DO UPDATE SET
                    status        = 'running',
                    current_round = 0,
                    participants  = excluded.participants,
                    started_at    = CURRENT_TIMESTAMP
            """, (channel_id, json.dumps(participants, ensure_ascii=False)))
            # Clear queue (participants ушли в бой)
            await conn.execute(
                "DELETE FROM bannerlord_tournament_queue WHERE channel_id=?",
                (channel_id,))
            await conn.commit()
        # Sprint 5.29 BLT-parity #5: achievement increment per participant
        try:
            from routes.bannerlord_achievements import increment_stat
            for p in participants:
                await increment_stat(channel_id, p, "tournament_participations", 1)
        except Exception:
            pass
        print(f"[bannerlord:{channel_id}] tournament started: "
              f"{len(participants)} participants ({participants[:3]}...)")

    async def _on_tournament_round_ended(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Конец раунда: resolve ставок текущего раунда + advance round_index.

        Payload: {round_index, survivors: [username...]}
        Bet wins если bettor.target ∈ survivors. Pot redistribution:
          payout = round((amount / sum(winning_amounts)) * total_pot)
        Если ни одной winning bet — pot crematorium (burn).
        """
        data = env.data
        try:
            round_index = int(data.get("round_index") or 0)
        except (TypeError, ValueError):
            return
        survivors = data.get("survivors") or []
        survivors_lower = {str(s).lower() for s in survivors}

        from dependencies import get_db
        async with get_db()._connect() as conn:
            # 2026-05-29 FIX («ставки сгорали»): НЕ резолвим ставки помачтево.
            # tournament.round_ended прилетает на КАЖДЫЙ match (Harmony
            # EndCurrentMatch postfix), а раунд = несколько матчей. Раньше на
            # первом матче мы резолвили ВСЕ ставки раунда против survivors
            # одного матча → ставки на победителей других матчей сгорали, и
            # current_round преждевременно advance'ился. Теперь ставки
            # резолвятся ТОЛЬКО в конце турнира по финальному победителю
            # (_on_tournament_ended, Predictions-style). Здесь — только advance
            # round_index (для bet dedup / UI).
            await conn.execute("""
                UPDATE bannerlord_tournament_state
                SET current_round = ?
                WHERE channel_id=?
            """, (round_index + 1, channel_id))
            await conn.commit()
        print(f"[bannerlord:{channel_id}] tournament round {round_index} ended, "
              f"{len(survivors_lower)} survivors (bets resolve at tournament end)")

    async def _on_tournament_ended(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Турнир закончился — финал ИЛИ aborted (стример вышел досрочно).

        Payload: {winner: username|null, participants: [...], aborted: bool}
        Backend записывает last_winner + status='idle' (готов к новому).
        Mod-side даёт hero.Gold + XP + prize item победителю.

        Aborted: any open bets refund'аются bettor'ам (бот не виноват что
        стример вышел). Также очищаем queue если осталась.
        """
        data = env.data
        winner = (data.get("winner") or "").lower() or None
        aborted = bool(data.get("aborted"))

        from dependencies import get_db
        async with get_db()._connect() as conn:
            # Aborted — прогнозы аннулируются (они бесплатные, возвращать нечего).
            if aborted:
                cur = await conn.execute(
                    "UPDATE bannerlord_tournament_bets SET resolved=2, payout=0 "
                    "WHERE channel_id=? AND resolved=0",
                    (channel_id,))
                if cur.rowcount:
                    print(f"[bannerlord:{channel_id}] tournament aborted — "
                          f"{cur.rowcount} open predictions voided")
            elif winner:
                # 1.5 compliance (2026-06-11): no-loss ПРОГНОЗЫ. Верный прогноз
                # (target == финальный winner) → фикс-бонус из платформенного
                # пула; неверный → ничего (зритель ничего не ставил, не теряет).
                # Без pot/burn — убрали wager-на-исход (дух §6.2.6).
                TOURNAMENT_PREDICTION_REWARD = 500   # крустиков за верный прогноз
                cur = await conn.execute("""
                    SELECT bettor, target, round_index
                    FROM bannerlord_tournament_bets
                    WHERE channel_id=? AND resolved=0
                """, (channel_id,))
                preds = await cur.fetchall()
                n_correct = 0
                for bettor, target, r_idx in preds:
                    correct = (target or "").lower() == winner
                    reward = TOURNAMENT_PREDICTION_REWARD if correct else 0
                    await conn.execute("""
                        UPDATE bannerlord_tournament_bets
                        SET resolved=?, payout=?
                        WHERE channel_id=? AND bettor=? AND round_index=?
                    """, (1 if correct else 2, reward, channel_id, bettor, r_idx))
                    if correct:
                        await conn.execute(
                            "UPDATE viewers SET points = points + ? "
                            "WHERE channel_id=? AND username=?",
                            (reward, channel_id, bettor))
                        n_correct += 1
                if preds:
                    print(f"[bannerlord:{channel_id}] tournament predictions resolved "
                          f"by winner @{winner}: {n_correct}/{len(preds)} correct "
                          f"(+{TOURNAMENT_PREDICTION_REWARD}⦷ each)")

            await conn.execute("""
                UPDATE bannerlord_tournament_state
                SET status='idle', last_winner=?, participants='[]', current_round=0
                WHERE channel_id=?
            """, (winner, channel_id))
            # Aborted — гарантированно чистим queue (на случай если start был, но roster generation failed)
            if aborted:
                await conn.execute(
                    "DELETE FROM bannerlord_tournament_queue WHERE channel_id=?",
                    (channel_id,))
            await conn.commit()
        await self._log_event(channel_id, "tournament.ended", winner, data)
        # Sprint 5.29 BLT-parity #5: achievement increment для winner
        if winner and not aborted:
            try:
                from routes.bannerlord_achievements import increment_stat
                await increment_stat(channel_id, winner, "tournament_wins", 1)
            except Exception:
                pass

            # Sprint 5.32 (BLT-parity H8) — persistent anti-snowball counter.
            # bannerlord_heroes.tournament_wins → mod GET'ит при tournament
            # start как список "недавних winner'ов" → анти-сноубол HP penalty.
            # Раньше _recentWinners был static List в C# → сбрасывался на
            # reload save → доминирующий viewer переставал получать nerf.
            try:
                from dependencies import get_db
                async with get_db()._connect() as conn2:
                    await conn2.execute(
                        "UPDATE bannerlord_heroes "
                        "SET tournament_wins = tournament_wins + 1 "
                        "WHERE channel_id=? AND username=?",
                        (channel_id, winner))
                    await conn2.commit()
            except Exception as e:
                logger.warning("[bannerlord:%s] tournament_wins UPDATE failed for @%s: %s",
                               channel_id, winner, e)

            # Phase B (inventory unification) — победитель получает предмет в
            # тот же инвентарь, что и кузница (source='tournament').
            try:
                from routes.bannerlord_custom_items import (
                    generate_prize_item, insert_custom_item)
                from dependencies import get_db as _get_db
                prize = generate_prize_item()
                async with _get_db()._connect() as conn3:
                    await insert_custom_item(conn3, channel_id, winner, prize, "tournament")
                    await conn3.commit()
                logger.info("[bannerlord:%s] tournament prize → @%s: %s (%s)",
                            channel_id, winner, prize["custom_name"], prize["rarity"])
            except Exception as e:
                logger.warning("[bannerlord:%s] tournament prize failed for @%s: %s",
                               channel_id, winner, e)

        status_str = "ABORTED" if aborted else f"winner=@{winner}"
        print(f"[bannerlord:{channel_id}] tournament ended ({status_str})")

    # ── Sprint 5.32 (BLT-parity M2): heir queue ───────────────────────────────

    async def _on_heir_came_of_age(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит когда ребёнок adopted hero'я достиг 18 лет.

        Payload: {parent_username, heir_hero_id, heir_name}.
        INSERT в bannerlord_heirs. PRIMARY KEY (channel_id, heir_hero_id) защищает
        от дублей. Frontend GET /api/bannerlord/heirs?username=… подтянет list.
        """
        data = env.data
        parent_username = (data.get("parent_username") or "").lower()
        heir_hero_id = (data.get("heir_hero_id") or "").strip()
        heir_name = (data.get("heir_name") or "").strip() or heir_hero_id

        # Sprint 5.32 (LOG-3) — entry log с params чтобы trace heir-flow в логах.
        logger.info("[HEIR-COMA] ch=%s parent=@%s heir='%s' (id=%s) entering...",
                    channel_id, parent_username, heir_name, heir_hero_id)

        if not parent_username or not heir_hero_id:
            logger.warning("[HEIR-COMA] ch=%s missing parent/heir: %s",
                           channel_id, data)
            return

        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute("""
                INSERT INTO bannerlord_heirs
                    (channel_id, parent_username, heir_hero_id, heir_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_id, heir_hero_id) DO UPDATE SET
                    heir_name = excluded.heir_name,
                    alive     = 1
            """, (channel_id, parent_username, heir_hero_id, heir_name))
            await conn.commit()

        await self._log_event(channel_id, "hero.heir_came_of_age", parent_username, data)
        print(f"[HEIR-COMA] ch={channel_id} parent=@{parent_username} "
              f"heir={heir_name} ({heir_hero_id}) INSERTED OK")

    async def _on_heir_died(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит когда heir умер ДО succession (engine killed via plague/war/etc.).

        Payload: {heir_hero_id}. UPDATE alive=0 — не показываем в очереди больше.
        """
        data = env.data
        heir_hero_id = (data.get("heir_hero_id") or "").strip()
        if not heir_hero_id:
            logger.warning("[HEIR-DIED] ch=%s missing heir_hero_id", channel_id)
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            cur = await conn.execute(
                "UPDATE bannerlord_heirs SET alive=0 "
                "WHERE channel_id=? AND heir_hero_id=?",
                (channel_id, heir_hero_id))
            affected = cur.rowcount
            await conn.commit()
        await self._log_event(channel_id, "hero.heir_died", None, data)
        # Sprint 5.32 (LOG-3) — affected rowcount показывает был ли heir вообще
        # в нашей очереди. 0 = engine NPC death (не наш heir, нормально). >0 =
        # реально потеряли pre-collected heir'а (печально, но not critical).
        logger.info("[HEIR-DIED] ch=%s heir_id=%s affected=%d (0=NPC death not tracked, >0=our heir lost)",
                    channel_id, heir_hero_id, affected)

    # ── Sprint 5.33 (BLT-parity VAS): vassal lifecycle ────────────────────────

    @staticmethod
    async def _drop_placeholder_rows(conn, channel_id: int, action_id: str) -> None:
        """Действие не состоялось — закрыть всё, что было записано авансом.

        Два вида таких записей, и обе висли вечно:

        ЗАЯВКА НА МИР (`bannerlord_peace_offers`, статус 'pending'). Уникальный
        индекс частичный — только по 'pending', — поэтому висящая заявка не
        мусор, а замок: тот же король больше НИКОГДА не предложит мир той же
        фракции, вставка падает на UNIQUE и зритель читает «уже отправлен».
        Терминальный статус снимает замок. Связь по `action_id` появилась
        миграцией M101; у строк старше неё колонка пустая — их не трогаем,
        чтобы не закрыть чужое, разбор старых остаётся ручным.

        2026-07-28. Создание вассал-клана пишет строку `bannerlord_vassals` ДО
        того, как мод сходит в игру, с `vassal_clan_id = "pending_<action_id>"`.
        Подтверждения могло не быть вовсе (мод не нашёл наследника, игра закрыта,
        действие истекло по TTL) — и тогда строка оставалась навсегда: зритель
        видел вассала, которого в игре нет, наследник числился занятым, слот из
        пяти был съеден. На проде 27.07 так осело 5 фантомов.

        Отдельного поля-связи у строки нет, но заготовка сама несёт action_id в
        своём id — по нему и убираем. Транзакцию не открываем и не коммитим:
        вызывающий уже внутри своей.
        """
        cur = await conn.execute(
            "DELETE FROM bannerlord_vassals "
            "WHERE channel_id=? AND vassal_clan_id=?",
            (channel_id, f"pending_{action_id[:16]}"))
        if cur.rowcount:
            logger.info("[VAS-CLEANUP] ch=%s action=%s dropped %d placeholder row(s)",
                        channel_id, action_id, cur.rowcount)

        try:
            cur = await conn.execute(
                "UPDATE bannerlord_peace_offers SET status='rejected' "
                "WHERE channel_id=? AND action_id=? AND status='pending'",
                (channel_id, action_id))
            if cur.rowcount:
                logger.info("[PEACE-CLEANUP] ch=%s action=%s closed %d offer(s)",
                            channel_id, action_id, cur.rowcount)
        except Exception as ex:
            # Колонки может не быть, если миграция M101 ещё не прошла —
            # уборка вассалов из-за этого падать не должна.
            logger.warning("[PEACE-CLEANUP] ch=%s action=%s skipped: %s",
                           channel_id, action_id, ex)

    async def _on_vassal_created(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит после успешного создания vassal-clan'а в-game.
        Payload: {placeholder_clan_id, real_clan_id, parent_username, heir_hero_id, vassal_name}.
        Backend backfill'ит реальный Clan.StringId в bannerlord_vassals."""
        data = env.data
        placeholder = (data.get("placeholder_clan_id") or "").strip()
        real_clan_id = (data.get("real_clan_id") or "").strip()
        if not placeholder or not real_clan_id:
            logger.warning("[VAS-CREATED] ch=%s missing placeholder/real: %s",
                           channel_id, data)
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            cur = await conn.execute(
                "UPDATE bannerlord_vassals SET vassal_clan_id=? "
                "WHERE channel_id=? AND vassal_clan_id=?",
                (real_clan_id, channel_id, placeholder))
            affected = cur.rowcount
            await conn.commit()
        await self._log_event(channel_id, "hero.vassal_created", None, data)
        logger.info("[VAS-CREATED] ch=%s placeholder=%s → real=%s affected=%d",
                    channel_id, placeholder, real_clan_id, affected)

    # ── Sprint 5.33 (BLT-parity SHOP): workshop daily profit sync ─────────────

    async def _on_workshop_profit_sync(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит OnDailyTick: {owner, settlement_id, workshop_type, net_dinars}.
        Backend конвертирует net dinars → crustic, credit'ит viewer.

        Resolve DB row через (channel, owner, settlement_id, workshop_type) —
        UNIQUE partial idx гарантирует один active.
        """
        data = env.data
        owner = (data.get("owner") or env.user or "").strip().lower()
        settlement_id = (data.get("settlement_id") or "").strip()
        workshop_type = (data.get("workshop_type") or "").strip()
        try:
            net_dinars = int(data.get("net_dinars") or 0)
        except (TypeError, ValueError):
            net_dinars = 0
        if not owner or not settlement_id or not workshop_type or net_dinars <= 0:
            return

        try:
            from dependencies import get_db as _gdb
            async with _gdb()._connect() as conn:
                cur = await conn.execute(
                    "SELECT id FROM bannerlord_workshops "
                    "WHERE channel_id=? AND owner_username=? "
                    "  AND settlement_id=? AND workshop_type=? "
                    "  AND status='active' LIMIT 1",
                    (channel_id, owner, settlement_id, workshop_type))
                row = await cur.fetchone()
            if not row:
                logger.warning("[SHOP-SYNC] no active row ch=%s @%s %s/%s",
                               channel_id, owner, settlement_id, workshop_type)
                return
            workshop_id = row[0]

            from routes.bannerlord_workshops import credit_workshop_profit
            crustic = await credit_workshop_profit(
                channel_id, owner, workshop_id, net_dinars)
            await self._log_event(channel_id, "hero.workshop_profit_sync", owner, {
                "workshop_id": workshop_id,
                "net_dinars":  net_dinars,
                "crustic":     crustic,
            })
            logger.info("[SHOP-SYNC] ch=%s @%s ws=%s +%d dinars → +%d⦷",
                        channel_id, owner, workshop_id, net_dinars, crustic)
        except Exception as ex:
            logger.exception("[SHOP-SYNC] failed ch=%s @%s %s/%s: %s",
                             channel_id, owner, settlement_id, workshop_type, ex)

    # ── Sprint 5.33 (BLT-parity FIEF): fief tribute daily sync ────────────────

    async def _on_fief_tribute_sync(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит OnDailyTick для каждого owned fief.
        Payload: {owner, fief_id, fief_name, fief_type [town/castle/village], net_dinars}.
        Backend UPSERT'ит row, применяет boost multiplier (если active), credit'ит crustic.
        """
        data = env.data
        owner = (data.get("owner") or env.user or "").strip().lower()
        fief_id = (data.get("fief_id") or "").strip()
        fief_name = (data.get("fief_name") or fief_id).strip()
        fief_type = (data.get("fief_type") or "town").strip().lower()
        try:
            net_dinars = int(data.get("net_dinars") or 0)
        except (TypeError, ValueError):
            net_dinars = 0
        if not owner or not fief_id or net_dinars <= 0:
            return
        try:
            from routes.bannerlord_fiefs import credit_fief_tribute
            crustic = await credit_fief_tribute(
                channel_id, owner, fief_id, fief_name, fief_type, net_dinars)
            await self._log_event(channel_id, "hero.fief_tribute_sync", owner, {
                "fief_id":    fief_id,
                "fief_type":  fief_type,
                "net_dinars": net_dinars,
                "crustic":    crustic,
            })
            logger.info("[FIEF-SYNC] ch=%s @%s %s/%s +%d dinars → +%d⦷",
                        channel_id, owner, fief_type, fief_name, net_dinars, crustic)
        except Exception as ex:
            logger.exception("[FIEF-SYNC] failed ch=%s @%s fief=%s: %s",
                             channel_id, owner, fief_id, ex)

    # ── Sprint 5.33 (BLT-parity CARAVAN): caravan lifecycle ───────────────────

    async def _on_caravan_created(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod confirms caravan party created → backfill engine StringId."""
        data = env.data
        try:
            caravan_id = int(data.get("caravan_id") or 0)
        except (TypeError, ValueError):
            caravan_id = 0
        party_id = (data.get("party_id") or "").strip()
        if caravan_id <= 0 or not party_id:
            logger.warning("[CARAVAN-CREATED] missing fields ch=%s data=%s", channel_id, data)
            return
        try:
            from routes.bannerlord_caravans import backfill_caravan_party_id
            await backfill_caravan_party_id(channel_id, caravan_id, party_id)
            await self._log_event(channel_id, "hero.caravan_created", env.user, {
                "caravan_id": caravan_id, "party_id": party_id,
            })
        except Exception as ex:
            logger.exception("[CARAVAN-CREATED] failed: %s", ex)

    async def _on_caravan_profit_sync(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Daily profit sync — mod diffs PartyTradeGold.
        Payload: {owner, party_id, net_dinars}."""
        data = env.data
        owner = (data.get("owner") or env.user or "").strip().lower()
        party_id = (data.get("party_id") or "").strip()
        try:
            net_dinars = int(data.get("net_dinars") or 0)
        except (TypeError, ValueError):
            net_dinars = 0
        if not owner or not party_id or net_dinars <= 0:
            return
        try:
            from routes.bannerlord_caravans import credit_caravan_profit
            crustic = await credit_caravan_profit(
                channel_id, owner, party_id, net_dinars)
            await self._log_event(channel_id, "hero.caravan_profit_sync", owner, {
                "party_id":    party_id,
                "net_dinars":  net_dinars,
                "crustic":     crustic,
            })
        except Exception as ex:
            logger.exception("[CARAVAN-SYNC] failed ch=%s @%s party=%s: %s",
                             channel_id, owner, party_id, ex)

    async def _on_caravan_destroyed(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Caravan party destroyed (bandits / war). Караван удаляется — слот
        владельца освобождается, зритель может создать новый.
        Payload: {party_id, captor_name (optional)}."""
        data = env.data
        party_id = (data.get("party_id") or "").strip()
        captor = (data.get("captor_name") or "").strip()
        if not party_id:
            return
        try:
            from routes.bannerlord_caravans import mark_caravan_destroyed
            await mark_caravan_destroyed(channel_id, party_id, captor)
            await self._log_event(channel_id, "hero.caravan_destroyed", env.user, {
                "party_id": party_id, "captor": captor,
            })
        except Exception as ex:
            logger.exception("[CARAVAN-DESTROYED] failed ch=%s party=%s: %s",
                             channel_id, party_id, ex)

    # ── Sprint 5.33 PORDER: party order status sync ──────────────────────────

    async def _on_party_order_status(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Mod пушит при set/release/expire/complete для sticky orders.

        Payload: {owner, order_type, target_id, target_name, remaining_hours}
          - order_type=None означает release/expire/complete → DB row → 'completed'
          - order_type set → DB row остаётся 'active' (insert уже сделан в handler)

        Зачем: extension polls /api/bannerlord/party-orders и видит actual state
        из mod-side (engine может auto-complete order до того как UI request'нет).
        """
        data = env.data
        owner = (data.get("owner") or env.user or "").strip().lower()
        order_type = data.get("order_type")  # может быть None
        if not owner:
            return

        try:
            from dependencies import get_db as _gdb
            async with _gdb()._connect() as conn:
                if order_type is None:
                    # Release/expire/complete — mark active row as completed.
                    await conn.execute(
                        "UPDATE bannerlord_party_orders SET status='completed' "
                        "WHERE channel_id=? AND owner_username=? AND status='active'",
                        (channel_id, owner))
                    await conn.commit()
            await self._log_event(channel_id, "hero.party_order_status", owner, {
                "order_type": order_type,
                "target_id":  data.get("target_id"),
                "target_name": data.get("target_name"),
                "remaining_hours": data.get("remaining_hours"),
            })
            logger.info("[PORDER-STATUS] ch=%s @%s order=%s target=%s remain=%s",
                        channel_id, owner, order_type or "released",
                        data.get("target_name") or "—",
                        data.get("remaining_hours"))
        except Exception as ex:
            logger.exception("[PORDER-STATUS] failed ch=%s @%s: %s",
                             channel_id, owner, ex)

    # ── Sprint 5.33 CATALOG-1: settlements catalog cache ─────────────────────

    # In-memory per-channel cache. Mod пушит один раз на game load.
    # Структура: { channel_id: { "updated_at": float, "settlements": [...] } }
    _settlements_cache: Dict[int, Dict[str, Any]] = {}

    async def _on_settlements_catalog(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Stores live engine settlements catalog для extension dropdown."""
        import time as _time
        data = env.data
        settlements = data.get("settlements") or []
        if not isinstance(settlements, list):
            logger.warning("[CATALOG] ch=%s settlements не list — skip", channel_id)
            return
        # Validate basic shape: { id, name, type, culture, faction, faction_n }
        clean = []
        for s in settlements:
            if not isinstance(s, dict): continue
            sid = (s.get("id") or "").strip()
            if not sid: continue
            clean.append({
                "id":        sid,
                "name":      (s.get("name") or sid),
                "type":      (s.get("type") or "other"),
                "culture":   s.get("culture") or "",
                "faction":   s.get("faction") or "",
                "faction_n": s.get("faction_n") or "",
            })
        self._settlements_cache[channel_id] = {
            "updated_at":  _time.time(),
            "settlements": clean,
        }
        logger.info("[CATALOG] ch=%s settlements cache updated: %d entries",
                    channel_id, len(clean))
        await self._log_event(channel_id, "world.settlements_catalog", env.user, {
            "count": len(clean),
        })

    def get_settlements(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Public accessor для endpoint."""
        return self._settlements_cache.get(channel_id)

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

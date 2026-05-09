"""
modules/bannerlord/_adapter.py — BannerlordAdapter (scaffold).

Stub-уровень для validation (step 6.c). handle_event логирует события без
записи в БД (нет bannerlord-specific схемы пока). dispatch_action использует
generic action queue (db.enqueue_action) — он game-agnostic, работает без
изменений как у RimWorld.

Когда реальный C# submodule появится:
1. Расширить handle_event обработкой hero.* events с записью в новые
   bannerlord_heroes / bannerlord_skills / etc. таблицы (новая миграция)
2. Создать новые db-helpers по типу upsert_player_pawn но для bannerlord
3. Тесты per-channel изоляции для bannerlord-таблиц
"""
from __future__ import annotations

from typing import Any, Dict

from .._base import ModuleAdapter, ModuleEnvelope


class BannerlordAdapter(ModuleAdapter):
    """Bannerlord-specific module adapter (scaffold)."""

    async def handle_event(self, channel_id: int, env: ModuleEnvelope) -> None:
        et = env.type
        if et == "module.heartbeat":
            return

        if et in ("module.session_start", "module.session_end"):
            print(f"[bannerlord:{channel_id}] {et} data={env.data}")
            return

        if et == "module.catalog_update":
            # Generic catalog работает как у RimWorld — переиспользуем
            # db.replace_module_catalog. Это и есть архитектурная валидация:
            # core-инфраструктура game-agnostic, не требует bannerlord-кода.
            from dependencies import get_db
            catalog_type = str(env.data.get("catalog") or "").lower()
            if catalog_type not in ("shop", "events"):
                print(f"[bannerlord:{channel_id}] catalog_update unknown type={catalog_type}, skip")
                return
            entries = env.data.get("entries") or []
            if not isinstance(entries, list):
                return
            inserted = await get_db().replace_module_catalog(
                channel_id=channel_id,
                module_id=self.id,
                catalog_type=catalog_type,
                entries=entries,
            )
            print(f"[bannerlord:{channel_id}] catalog_update type={catalog_type} entries={inserted}")
            return

        # Player events — пока log only. Реальные writes в bannerlord_heroes/...
        # требуют новой миграции и DB-helpers (отдельная задача после того как
        # C# submodule будет writeable).
        if et in ("player.linked", "player.unlinked", "player.state_update",
                   "player.died", "player.respawned"):
            print(f"[bannerlord:{channel_id}] {et} viewer={env.data.get('viewer_id', '?')} "
                  f"hero_ref={env.data.get('character_ref', '?')} (SCAFFOLD — no-op)")
            return

        # Bannerlord-specific extensions
        if et in ("hero.skill_changed", "hero.equipment_changed",
                   "hero.relation_changed", "hero.faction_changed"):
            print(f"[bannerlord:{channel_id}] extension {et} data={env.data} (SCAFFOLD — no-op)")
            return

        # World events
        if et == "world.event_occurred":
            print(f"[bannerlord:{channel_id}] world.event_occurred event_id={env.data.get('event_id')}")
            return

        print(f"[bannerlord:{channel_id}] WARN unhandled event type={et}")

    async def dispatch_action(self, channel_id: int, env: ModuleEnvelope) -> Dict[str, Any]:
        """Action queue работает identically с RimWorld — generic infra
        в module_actions table. Это архитектурная валидация: ОДИН код
        в db.enqueue_action обслуживает любой модуль.
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
            "queued": True,
            "action_id": env.id,
            "outbox_pk": pk,
            "module_id": self.id,
        }

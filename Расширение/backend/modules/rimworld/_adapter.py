"""
modules/rimworld/_adapter.py — RimWorldAdapter (ModuleAdapter implementation).

Step 2 status: handle_event теперь dispatcher по env.type. Реальные
implementations:
  - module.session_start  — clear session-scoped catalogs (MULTITENANT §H)
  - module.session_end    — log only (state остаётся для resume)
  - module.heartbeat      — no-op
Остальные событийные типы (player.linked/_died/_state_update + extension
pawn.*) — пока залогированы как received-but-not-handled. Имплементация
в Step 3-4 миграции (см. docs/MODULE_MIGRATION.md).

dispatch_action остаётся stub'ом до Step 3 (action queue).
"""
from __future__ import annotations

from typing import Any, Dict

from .._base import ModuleAdapter, ModuleEnvelope


class RimWorldAdapter(ModuleAdapter):
    """RimWorld-specific module adapter."""

    async def handle_event(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Dispatch по env.type. Module API §7 standard events + extension
        events декларированные в manifest.yaml.

        ВАЖНО: метод вызывается ПОСЛЕ того как routes/module_api.py уже
        вызвал on_session_start/_end (lifecycle hooks). Здесь — только
        бизнес-логика, не lifecycle.
        """
        et = env.type
        if et == "module.heartbeat":
            return  # no-op, ping для liveness check'а

        if et == "module.session_start":
            await self._on_session_start_business(channel_id, env)
            return

        if et == "module.session_end":
            print(f"[rimworld:{channel_id}] session_end reason={env.data.get('reason', 'graceful')}")
            return

        if et == "module.catalog_update":
            # Step 4 миграции: запись в session-scoped shop_catalog/event_catalog.
            # Сейчас — log + safe-skip (legacy /api/rimworld/catalog/* всё ещё
            # работает напрямую через rimworld.py).
            print(f"[rimworld:{channel_id}] catalog_update: catalog={env.data.get('catalog')} "
                  f"entries={len(env.data.get('entries') or [])}")
            return

        # ── Player events ──────────────────────────────────────────────
        if et in ("player.linked", "player.unlinked", "player.state_update",
                   "player.died", "player.respawned"):
            # Step 3 миграции: записывать в rimworld_pawns / pawn_skills / etc.
            # Сейчас legacy /api/rimworld/link, /api/rimworld/sync_pawns делают
            # это напрямую — не дублируем чтобы не было двойной записи.
            print(f"[rimworld:{channel_id}] {et} viewer={env.data.get('viewer_id', '?')} "
                  f"char={env.data.get('character_ref', '?')} (NOT_PROCESSED — legacy path active)")
            return

        # ── Extension events (RimWorld-specific) ──────────────────────
        if et in ("pawn.trait_changed", "pawn.implant_installed",
                   "pawn.gene_changed", "pawn.xenotype_changed"):
            print(f"[rimworld:{channel_id}] extension {et} data={env.data} "
                  f"(NOT_PROCESSED — Step 3 will route)")
            return

        # Unknown тип, не покрыт в manifest'е — manifest.supports_event уже
        # отверг бы это в routes/module_api.py. Сюда попасть не должно.
        print(f"[rimworld:{channel_id}] WARN unhandled event type={et}")

    async def _on_session_start_business(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Session-scoped catalog cleanup per docs/MULTITENANT_PLAN.md §H.

        При новой игровой сессии стримера — sсрасываем кэшированные каталоги
        и пешки. Они пере-публикуются модом через module.catalog_update +
        player.linked в новой сессии.

        TODO: дёрнуть `db.clear_rimworld_session(channel_id)` который
        выполнит DELETE FROM shop_catalog/_events_catalog/_pawns где
        channel_id = X. Method ещё не добавлен в database.py — Step 4
        миграции.
        """
        seed = env.data.get("game_seed", "")
        world = env.data.get("world_name", "")
        print(f"[rimworld:{channel_id}] session_start seed={seed} world={world} "
              f"(TODO: clear session-scoped catalogs in Step 4)")

    async def dispatch_action(self, channel_id: int, env: ModuleEnvelope) -> Dict[str, Any]:
        """Stub до Step 3. До action queue actions исполняются прямыми
        /api/rimworld/<verb> вызовами."""
        return {"queued": False, "reason": "not_implemented_yet", "action_id": env.id}

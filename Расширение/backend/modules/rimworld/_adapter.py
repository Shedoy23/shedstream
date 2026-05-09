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
            # Step 4: запись в module_catalogs (generic table). Replace-
            # семантика — новый catalog_update полностью заменяет
            # существующий per (channel, module, catalog_type).
            await self._on_catalog_update(channel_id, env)
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

        При новой игровой сессии стримера — сбрасываем кэшированные каталоги.
        Connector пере-публикует актуальные через `module.catalog_update`
        в новой сессии.

        ВАЖНО: чистим только Module-API каталоги (`module_catalogs` table).
        Legacy таблицы (shop_catalog, rimworld_event_catalog) — НЕ трогаем
        в этом коммите. Step 5/6 wrapper migration переведёт legacy чтения
        на module_catalogs, тогда устаревшие таблицы можно сбросить.

        Pawns (rimworld_pawns + связанные) — тоже не трогаем здесь, это
        обязанность Step 5 когда player.linked/_died начнут писать через
        Module API.
        """
        seed = env.data.get("game_seed", "")
        world = env.data.get("world_name", "")
        from dependencies import get_db
        db = get_db()
        cleared = await db.clear_module_catalogs(channel_id, self.id)
        print(f"[rimworld:{channel_id}] session_start seed={seed} world={world} "
              f"(cleared {cleared} catalog entries)")

    async def _on_catalog_update(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Step 4: replace module_catalogs для (channel, rimworld, type).

        env.data: {catalog: 'shop'|'events', entries: [{id, ...}, ...]}.
        Replace-семантика — полная замена существующих entries.
        """
        from dependencies import get_db
        catalog_type = str(env.data.get("catalog") or "").lower()
        if catalog_type not in ("shop", "events"):
            print(f"[rimworld:{channel_id}] catalog_update: unknown catalog={catalog_type!r}, skip")
            return
        entries = env.data.get("entries") or []
        if not isinstance(entries, list):
            print(f"[rimworld:{channel_id}] catalog_update: entries not list, skip")
            return
        db = get_db()
        inserted = await db.replace_module_catalog(
            channel_id=channel_id,
            module_id=self.id,
            catalog_type=catalog_type,
            entries=entries,
        )
        print(f"[rimworld:{channel_id}] catalog_update: type={catalog_type} entries={inserted} (replaced)")

    async def dispatch_action(self, channel_id: int, env: ModuleEnvelope) -> Dict[str, Any]:
        """Step 3: enqueue в module_actions outbox.

        Connector long-poll'ит `GET /v1/module/rimworld/actions` и забирает.
        Когда исполнит — POST'ит /v1/module/rimworld/ack {action_id, success}.

        Validation: тип action должен быть declared в manifest.actions/extensions.
        """
        if not self.manifest.supports_action(env.type):
            return {
                "queued": False,
                "reason": "action_not_in_manifest",
                "action_id": env.id,
                "type": env.type,
            }
        # Late-import чтобы избежать циклической зависимости modules ↔ dependencies.
        from dependencies import get_db
        db = get_db()
        pk = await db.enqueue_action(
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

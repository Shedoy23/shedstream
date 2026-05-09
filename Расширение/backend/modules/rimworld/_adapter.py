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

        # ── Player events (Step 5) ─────────────────────────────────────
        if et in ("player.linked", "player.unlinked", "player.state_update",
                   "player.died", "player.respawned"):
            await self._on_player_event(channel_id, env)
            return

        # ── Extension events (RimWorld-specific) ───────────────────────
        # Step 5 не покрывает — pawn-skill/trait/gene/implant/xenotype updates
        # требуют записи в rimworld_pawn_* таблицы которые легаси rimworld.py
        # уже наполняет при /api/rimworld/sync_pawns_bulk. Перевод на
        # Module-API-only path = Step 6 wrapper migration. Пока — log+skip.
        if et in ("pawn.trait_changed", "pawn.implant_installed",
                   "pawn.gene_changed", "pawn.xenotype_changed"):
            print(f"[rimworld:{channel_id}] extension {et} data={env.data} "
                  f"(NOT_PROCESSED — Step 6 will route)")
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

    async def _on_player_event(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Step 5: реагируем на player.linked/_unlinked/_state_update/_died/
        _respawned. Под feature flag MODULE_API_PLAYER_EVENTS_ENABLED.

        При false (default): log only — легаси /api/rimworld/link и
        sync_pawns_bulk продолжают наполнять rimworld_pawns как раньше.
        При true: пишем через db helpers (Step 5). Двойная запись с легаси
        путём допустима — UPSERT idempotent, последняя запись побеждает.

        После Step 6 wrapper migration легаси вызовы либо удаляются, либо
        форвардятся в Module API path → флаг становится постоянно true.
        """
        from config import MODULE_API_PLAYER_EVENTS_ENABLED
        viewer_id = str(env.data.get("viewer_id", "")).strip().lower()
        character_ref = str(env.data.get("character_ref", "")).strip()

        if not MODULE_API_PLAYER_EVENTS_ENABLED:
            print(f"[rimworld:{channel_id}] {env.type} viewer={viewer_id} char={character_ref} "
                  f"(SKIPPED — MODULE_API_PLAYER_EVENTS_ENABLED=false, legacy path active)")
            return

        if not viewer_id:
            print(f"[rimworld:{channel_id}] {env.type}: viewer_id required, skip")
            return

        from dependencies import get_db
        db = get_db()
        et = env.type

        if et == "player.linked":
            if not character_ref:
                print(f"[rimworld:{channel_id}] player.linked: character_ref required")
                return
            ok = await db.upsert_player_pawn(
                channel_id=channel_id,
                viewer_id=viewer_id,
                character_ref=character_ref,
                is_alive=True,
                health=1.0,
            )
            print(f"[rimworld:{channel_id}] player.linked viewer={viewer_id} char={character_ref} ok={ok}")
            return

        if et == "player.unlinked":
            ok = await db.remove_player_pawn(channel_id=channel_id, viewer_id=viewer_id)
            print(f"[rimworld:{channel_id}] player.unlinked viewer={viewer_id} ok={ok}")
            return

        if et == "player.state_update":
            # state_update может прийти без character_ref если pawn уже linked.
            # Если character_ref передан — обновляем (rename pawn возможен).
            health = float(env.data.get("health_pct") or 1.0)
            alive = bool(env.data.get("alive", True))
            if character_ref:
                ok = await db.upsert_player_pawn(
                    channel_id=channel_id,
                    viewer_id=viewer_id,
                    character_ref=character_ref,
                    is_alive=alive,
                    health=health,
                )
            else:
                ok = await db.mark_player_alive(channel_id=channel_id, viewer_id=viewer_id, alive=alive)
            print(f"[rimworld:{channel_id}] player.state_update viewer={viewer_id} alive={alive} hp={health:.2f} ok={ok}")
            return

        if et == "player.died":
            ok = await db.mark_player_alive(channel_id=channel_id, viewer_id=viewer_id, alive=False)
            print(f"[rimworld:{channel_id}] player.died viewer={viewer_id} cause={env.data.get('cause', '?')} ok={ok}")
            return

        if et == "player.respawned":
            ok = await db.mark_player_alive(channel_id=channel_id, viewer_id=viewer_id, alive=True)
            print(f"[rimworld:{channel_id}] player.respawned viewer={viewer_id} ok={ok}")
            return

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

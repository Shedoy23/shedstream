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

dispatch_action РЕАЛИЗОВАН (Step 3): кладёт в module_actions, мод забирает
long-poll'ом GET /v1/module/rimworld/actions и подтверждает POST .../ack.
Проверено эфиром 2026-09-05: 630 команд, 630 ACK через Module API, ни одного
через legacy /api/rimworld/ack-command, очередь rimworld_pending_commands пуста.
На legacy пока остаются: покупки (/api/rimworld/<действие>), состояние пешек
(sync-pawn/sync-pawns), каталоги, heartbeat/status/session-start/offline.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from .._base import ModuleAdapter, ModuleEnvelope, refund_still_due
from notices import add_notice_tx
from .refusals import describe as describe_refusal


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
        if et == "action.failed":
            await self._on_action_failed(channel_id, env)
            return

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

        # ── Extension events (RimWorld-specific, Step 6.a) ─────────────
        # Реальные writes в rimworld_pawn_traits / _genes / _hediffs под
        # тем же feature flag MODULE_API_PLAYER_EVENTS_ENABLED. При false —
        # log only (легаси /api/rimworld/sync_pawns_bulk наполняет).
        if et in ("pawn.trait_changed", "pawn.implant_installed",
                   "pawn.gene_changed", "pawn.xenotype_changed"):
            await self._on_pawn_extension_event(channel_id, env)
            return

        # Unknown тип, не покрыт в manifest'е — manifest.supports_event уже
        # отверг бы это в routes/module_api.py. Сюда попасть не должно.
        print(f"[rimworld:{channel_id}] WARN unhandled event type={et}")

    async def _on_action_failed(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Atomically refund a paid generic action, including progressive price state."""
        action_id = str(env.data.get("action_id") or "")
        reason = str(env.data.get("reason") or "failed")[:500]
        if not action_id:
            return
        from dependencies import get_db
        db = get_db()
        async with db._connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            if not await refund_still_due(conn, "rimworld", channel_id, action_id, reason):
                await conn.execute("ROLLBACK")
                print(f"[rimworld:{channel_id}] action.failed {action_id}: игра забрала "
                      f"заявку раньше сторожа — возврата нет")
                return
            cur = await conn.execute(
                "SELECT data,error_msg,type FROM module_actions "
                "WHERE channel_id=? AND module_id='rimworld' AND action_id=?",
                (channel_id, action_id))
            row = await cur.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return
            data_raw, previous_error, action_type = row
            if previous_error and str(previous_error).startswith("REFUNDED:"):
                await conn.execute("ROLLBACK")
                return
            try:
                data = json.loads(data_raw or "{}")
            except (TypeError, ValueError):
                data = {}
            price = int(data.get("price") or 0)
            username = str(data.get("initiated_by") or data.get("username") or "").lower()
            if price > 0 and username:
                await db.add_points_tx(conn, username, price, channel_id)
                category = {"add_gene": "gene", "add_trait": "trait"}.get(action_type)
                if category:
                    await db.decrement_purchase_count_tx(
                        conn, username, category, channel_id)
                marker = f"REFUNDED:{price} reason={reason}"
            else:
                marker = f"REFUNDED:0 (no_price) reason={reason}"
            await conn.execute(
                "UPDATE module_actions SET status='failed',error_msg=?,acked_at=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND module_id='rimworld' AND action_id=?",
                (marker, channel_id, action_id))
            # Объяснение уезжает зрителю ТОЙ ЖЕ транзакцией, что и деньги
            # (как в Bannerlord). Найдено постстрим-триажом 09.09: отказ в
            # RimWorld возвращал крустики МОЛЧА — за эфир два возврата и ноль
            # уведомлений. Зритель видит уход и возврат денег без единого
            # слова и жмёт снова; ровно ради этого заведён M103.
            await add_notice_tx(
                conn, channel_id, username, "refused",
                describe_refusal(reason), 0)
            await conn.commit()
        print(f"[rimworld:{channel_id}] action.failed {action_id} reason={reason} "
              f"refund={price if price > 0 else 0} user=@{username or '?'}")

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

    async def _on_pawn_extension_event(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Step 6.a: pawn.* RimWorld-specific extension events.

        env.data контракт:
          pawn.trait_changed  : {viewer_id, action: 'add'|'remove', trait_def, degree?, label?, description?}
          pawn.gene_changed   : {viewer_id, action: 'add'|'remove', def_name, label?, is_active?, xenogene?, gene_class?}
          pawn.implant_installed: {viewer_id, body_part, hediff_label, severity?, icon?, description?}
          pawn.xenotype_changed: {viewer_id, xenotype} — пока log only (нет dedicated DB column)

        Под flag MODULE_API_PLAYER_EVENTS_ENABLED. False = log only (легаси
        sync_pawns_bulk наполняет таблицы).
        """
        from config import MODULE_API_PLAYER_EVENTS_ENABLED
        from dependencies import get_db
        viewer_id = str(env.data.get("viewer_id", "")).strip().lower()
        if not viewer_id:
            print(f"[rimworld:{channel_id}] {env.type}: viewer_id required")
            return

        if not MODULE_API_PLAYER_EVENTS_ENABLED:
            print(f"[rimworld:{channel_id}] {env.type} viewer={viewer_id} data={env.data} "
                  f"(SKIPPED — MODULE_API_PLAYER_EVENTS_ENABLED=false)")
            return

        db = get_db()
        et = env.type
        action = str(env.data.get("action") or "add").lower()  # add | remove

        if et == "pawn.trait_changed":
            trait_def = str(env.data.get("trait_def", "")).strip()
            if not trait_def:
                print(f"[rimworld:{channel_id}] pawn.trait_changed: trait_def required")
                return
            if action == "remove":
                ok = await db.remove_pawn_trait(channel_id, viewer_id, trait_def)
            else:
                ok = await db.add_pawn_trait(
                    channel_id=channel_id, viewer_id=viewer_id, trait_def=trait_def,
                    degree=int(env.data.get("degree") or 0),
                    label=env.data.get("label"),
                    description=env.data.get("description"),
                )
            print(f"[rimworld:{channel_id}] pawn.trait_changed action={action} "
                  f"viewer={viewer_id} trait={trait_def} ok={ok}")
            return

        if et == "pawn.gene_changed":
            def_name = str(env.data.get("def_name", "")).strip()
            if not def_name:
                print(f"[rimworld:{channel_id}] pawn.gene_changed: def_name required")
                return
            if action == "remove":
                ok = await db.remove_pawn_gene(channel_id, viewer_id, def_name)
            else:
                ok = await db.add_pawn_gene(
                    channel_id=channel_id, viewer_id=viewer_id, def_name=def_name,
                    label=env.data.get("label"),
                    is_active=bool(env.data.get("is_active", True)),
                    xenogene=bool(env.data.get("xenogene", True)),
                    gene_class=env.data.get("gene_class"),
                )
            print(f"[rimworld:{channel_id}] pawn.gene_changed action={action} "
                  f"viewer={viewer_id} def={def_name} ok={ok}")
            return

        if et == "pawn.implant_installed":
            hediff_label = str(env.data.get("hediff_label", "")).strip()
            if not hediff_label:
                print(f"[rimworld:{channel_id}] pawn.implant_installed: hediff_label required")
                return
            ok = await db.add_pawn_implant(
                channel_id=channel_id, viewer_id=viewer_id,
                body_part=str(env.data.get("body_part") or ""),
                hediff_label=hediff_label,
                severity=float(env.data.get("severity") or 0.0),
                icon=str(env.data.get("icon") or "🦾"),
                is_permanent=bool(env.data.get("is_permanent", True)),
                description=env.data.get("description"),
            )
            print(f"[rimworld:{channel_id}] pawn.implant_installed viewer={viewer_id} "
                  f"label={hediff_label} ok={ok}")
            return

        if et == "pawn.xenotype_changed":
            # TODO: dedicated DB column в rimworld_pawns. Пока log only —
            # xenotype информация доступна через rimworld_pawn_genes WHERE
            # gene_class = 'Xenotype' (косвенно).
            print(f"[rimworld:{channel_id}] pawn.xenotype_changed viewer={viewer_id} "
                  f"xenotype={env.data.get('xenotype', '?')} (no dedicated DB column yet)")
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

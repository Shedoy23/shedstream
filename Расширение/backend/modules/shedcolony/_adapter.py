"""
modules/shedcolony/_adapter.py — ShedColony module adapter (core-side).

Зеркалит проверенный bannerlord-паттерн (modules/bannerlord/_adapter.py):
  • handle_event   — диспетчит по env.type → персистит в shedcolony_* таблицы (m83)
  • dispatch_action — кладёт action в общую очередь module_actions (мод забирает поллингом)

channel_id приходит уже валидированным из routes/module_api.py (из module-token).
Game-side connector — NeoForge-мод (D:\\sheddev\\shedcolony).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from .._base import ModuleAdapter, ModuleEnvelope

logger = logging.getLogger("rimlink.modules.shedcolony")


class ShedColonyAdapter(ModuleAdapter):

    async def handle_event(self, channel_id: int, env: ModuleEnvelope) -> None:
        et = env.type

        # Lifecycle (module.*) — базовые хуки уже отработали в module_api.py.
        if et in ("module.heartbeat", "module.session_start", "module.session_end"):
            return

        if et == "player.linked":
            await self._on_player_linked(channel_id, env)
        elif et == "player.died":
            await self._on_player_died(channel_id, env)
        elif et == "colonist.state":
            await self._on_colonist_state(channel_id, env)
        elif et == "colony.snapshot":
            await self._on_colony_snapshot(channel_id, env)
        elif et == "colony.capacity":
            await self._on_colony_capacity(channel_id, env)
        elif et == "action.failed":
            await self._on_action_failed(channel_id, env)
        else:
            logger.warning("[shedcolony:%s] unhandled event type=%s", channel_id, et)

    # ── event handlers ───────────────────────────────────────────────────────

    async def _on_player_linked(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Колонист зрителя создан и привязан. UPSERT в link-таблицу."""
        d = env.data
        viewer_id = (d.get("viewer_id") or d.get("username") or "").lower()
        citizen_id = str(d.get("citizen_id") or "")
        colony_id = str(d.get("colony_id") or "")
        colony_dim = d.get("colony_dim")
        if not viewer_id or not citizen_id:
            logger.warning("[shedcolony:%s] player.linked missing viewer_id/citizen_id: %s",
                           channel_id, d)
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            # ON CONFLICT(channel_id, viewer_id) — пере-привязка (после смерти/реролла).
            await conn.execute("""
                INSERT INTO shedcolony_colony_link
                    (channel_id, viewer_id, citizen_id, colony_id, colony_dim, status)
                VALUES (?, ?, ?, ?, ?, 'active')
                ON CONFLICT(channel_id, viewer_id) DO UPDATE SET
                    citizen_id = excluded.citizen_id,
                    colony_id  = excluded.colony_id,
                    colony_dim = excluded.colony_dim,
                    status     = 'active',
                    died_at    = NULL,
                    linked_at  = CURRENT_TIMESTAMP
            """, (channel_id, viewer_id, citizen_id, colony_id, colony_dim))
            await conn.commit()
        logger.info("[shedcolony:%s] player.linked @%s → citizen=%s", channel_id, viewer_id, citizen_id)

    async def _on_player_died(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Колонист зрителя погиб. Помечаем link как dead."""
        d = env.data
        viewer_id = (d.get("viewer_id") or d.get("username") or "").lower()
        citizen_id = str(d.get("citizen_id") or "")
        from dependencies import get_db
        async with get_db()._connect() as conn:
            if viewer_id:
                await conn.execute(
                    "UPDATE shedcolony_colony_link SET status='dead', died_at=CURRENT_TIMESTAMP "
                    "WHERE channel_id=? AND viewer_id=?", (channel_id, viewer_id))
            elif citizen_id:
                await conn.execute(
                    "UPDATE shedcolony_colony_link SET status='dead', died_at=CURRENT_TIMESTAMP "
                    "WHERE channel_id=? AND citizen_id=?", (channel_id, citizen_id))
            await conn.commit()
        logger.info("[shedcolony:%s] player.died @%s/%s", channel_id, viewer_id, citizen_id)

    async def _on_colonist_state(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Снимок состояния колониста. UPSERT в state-таблицу."""
        d = env.data
        citizen_id = str(d.get("citizen_id") or "")
        if not citizen_id:
            return
        skills = d.get("skills")
        skills_json = json.dumps(skills) if skills is not None else None
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute("""
                INSERT INTO shedcolony_colonist_state
                    (channel_id, citizen_id, hp, job, skills_json, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(channel_id, citizen_id) DO UPDATE SET
                    hp = excluded.hp,
                    job = excluded.job,
                    skills_json = excluded.skills_json,
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
            """, (channel_id, citizen_id, d.get("hp"), d.get("job"), skills_json,
                  d.get("status") or "active"))
            await conn.commit()

    async def _on_colony_snapshot(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Полный список колонистов на старте сессии — для reconciliation.
        MVP: логируем размер; пер-колонист state придёт отдельными colonist.state."""
        colonists = env.data.get("colonists") or []
        logger.info("[shedcolony:%s] colony.snapshot — %d colonists", channel_id, len(colonists))

    async def _on_colony_capacity(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Снимок свободных слотов колонии (мод шлёт периодически) → slot-availability UI.
        data: {jobs:[{job, free, total}], free_beds, total_beds}. Полная замена снимка."""
        d = env.data
        jobs = d.get("jobs") or []
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute("DELETE FROM shedcolony_capacity WHERE channel_id=?", (channel_id,))
            for j in jobs:
                await conn.execute(
                    "INSERT INTO shedcolony_capacity (channel_id, job_key, free_slots, total_slots) "
                    "VALUES (?, ?, ?, ?)",
                    (channel_id, str(j.get("job") or ""),
                     int(j.get("free") or 0), int(j.get("total") or 0)))
            await conn.execute(
                "INSERT INTO shedcolony_capacity_meta (channel_id, free_beds, total_beds, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "    free_beds = excluded.free_beds, total_beds = excluded.total_beds, "
                "    updated_at = CURRENT_TIMESTAMP",
                (channel_id, int(d.get("free_beds") or 0), int(d.get("total_beds") or 0)))
            await conn.commit()

    async def _on_action_failed(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Платный action провалился (ack success=false / action.failed) → РЕФАНД крустиков.
        Берёт price + initiated_by из сохранённого module_actions.data. Idempotent по 'REFUNDED:'.
        Зеркалит bannerlord (compliance: зритель не платит за невыполненное действие)."""
        action_id = env.data.get("action_id") or ""
        reason = env.data.get("reason") or "failed"
        if not action_id:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            cur = await conn.execute(
                "SELECT data, error_msg FROM module_actions "
                "WHERE channel_id=? AND module_id='shedcolony' AND action_id=?",
                (channel_id, action_id))
            row = await cur.fetchone()
            if not row:
                return
            data_str, error_msg = row
            if error_msg and error_msg.startswith("REFUNDED:"):
                return  # already refunded — idempotent
            try:
                parsed = json.loads(data_str or "{}")
            except Exception:
                parsed = {}
            price = int(parsed.get("price") or 0)
            username = (parsed.get("initiated_by") or "").lower()
            if price > 0 and username:
                await conn.execute(
                    "UPDATE viewers SET points = points + ? WHERE channel_id=? AND username=?",
                    (price, channel_id, username))
                marker = f"REFUNDED:{price} reason={reason}"
            else:
                marker = f"REFUNDED:0 (no_price) reason={reason}"
            await conn.execute(
                "UPDATE module_actions SET status='failed', error_msg=? "
                "WHERE channel_id=? AND module_id='shedcolony' AND action_id=?",
                (marker, channel_id, action_id))
            await conn.commit()
        logger.info("[shedcolony:%s] action.failed %s reason=%s → refund %s to @%s",
                    channel_id, action_id, reason, price if price > 0 else 0, username or "?")

    # ── action dispatch (→ outbox queue module_actions) ──────────────────────

    async def dispatch_action(self, channel_id: int, env: ModuleEnvelope) -> Dict[str, Any]:
        if not self.manifest.supports_action(env.type):
            return {"queued": False, "reason": "action_not_in_manifest",
                    "action_id": env.id, "type": env.type}
        from dependencies import get_db
        pk = await get_db().enqueue_action(
            channel_id=channel_id,
            module_id=self.id,
            action_id=env.id,
            action_type=env.type,
            data=env.data,
        )
        return {"queued": True, "action_id": env.id, "outbox_pk": pk, "module_id": self.id}

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
        elif et == "action.failed":
            logger.warning("[shedcolony:%s] action.failed: %s", channel_id, env.data)
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

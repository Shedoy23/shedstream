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

from .._base import ModuleAdapter, ModuleEnvelope, refund_still_due
from notices import add_notice_tx
from .refusals import describe as describe_refusal

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
        elif et == "colony.targets":
            await self._on_colony_targets(channel_id, env)
        elif et == "colony.catalog":
            await self._on_colony_catalog(channel_id, env)
        elif et == "action.failed":
            await self._on_action_failed(channel_id, env)
        else:
            logger.warning("[shedcolony:%s] unhandled event type=%s", channel_id, et)

    # ── event handlers ───────────────────────────────────────────────────────

    async def _on_player_linked(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Колонист зрителя создан и привязан. UPSERT в link-таблицу."""
        d = env.data
        # World-guard (аудит 2026-07-04): player.linked буферизуется модом при обрывах и может
        # приехать ПОСЛЕ смены мира. ДРОПАЕМ событие чужого мира (НЕ _check_world_switch — иначе
        # опоздавшее событие «переключило» бы канал назад и вайпнуло новый мир).
        if not await self._world_matches(channel_id, d.get("world_id")):
            logger.warning("[shedcolony:%s] player.linked from a STALE world dropped: %s",
                           channel_id, d.get("world_id"))
            return
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
            # TAKEOVER: a citizen_id belongs to exactly one viewer (UNIQUE constraint). If ANOTHER
            # viewer still holds this id, their colonist was recycled away by MineColonies (the id got
            # reused for this new spawn) — release their stale claim so the new owner can take it.
            # DELETE (not mark 'dead'): a 'dead' row still occupies UNIQUE(channel_id, citizen_id), so
            # the recycled id could never be re-linked → the new owner's INSERT would fail silently and
            # the stale owner would keep controlling the reused colonist. THIS was the 2026-06-27
            # shedoy23→bapah bug (bapah spawned on shedoy23's recycled citizen 1, INSERT blocked).
            await conn.execute(
                "DELETE FROM shedcolony_colony_link "
                "WHERE channel_id=? AND citizen_id=? AND viewer_id<>?",
                (channel_id, citizen_id, viewer_id))
            # ON CONFLICT(channel_id, viewer_id) — пере-привязка того же зрителя (после смерти/реролла).
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
        """Колонист зрителя погиб. Помечаем link как dead + чистим его state-строку: MineColonies
        рециклит citizen_id, и без чистки НОВЫЙ владелец рециклнутого id мигал бы hp/скиллами
        МЁРТВОГО колониста до первого свежего colonist.state (аудит 2026-07-04)."""
        d = env.data
        viewer_id = (d.get("viewer_id") or d.get("username") or "").lower()
        citizen_id = str(d.get("citizen_id") or "")
        from dependencies import get_db
        async with get_db()._connect() as conn:
            if viewer_id:
                await conn.execute(
                    "UPDATE shedcolony_colony_link SET status='dead', died_at=CURRENT_TIMESTAMP "
                    "WHERE channel_id=? AND viewer_id=? AND status='active'", (channel_id, viewer_id))
            elif citizen_id:
                await conn.execute(
                    "UPDATE shedcolony_colony_link SET status='dead', died_at=CURRENT_TIMESTAMP "
                    "WHERE channel_id=? AND citizen_id=? AND status='active'", (channel_id, citizen_id))
            if citizen_id:
                await conn.execute(
                    "DELETE FROM shedcolony_colonist_state WHERE channel_id=? AND citizen_id=?",
                    (channel_id, citizen_id))
            await conn.commit()
        logger.info("[shedcolony:%s] player.died @%s/%s", channel_id, viewer_id, citizen_id)

    async def _on_colonist_state(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Снимок состояния колониста. UPSERT в state-таблицу.
        Полный блоб (hp/max_hp/saturation/happiness/флаги/job/все скиллы) кладём в state_json —
        его показывает расширение; hp/job/skills_json дублируем в колонки для back-compat."""
        d = env.data
        citizen_id = str(d.get("citizen_id") or "")
        if not citizen_id:
            return
        if not await self._world_matches(channel_id, d.get("world_id")):
            return   # late state from a previous world — never resurrect stale data
        skills = d.get("skills")
        skills_json = json.dumps(skills) if skills is not None else None
        state_json = json.dumps(d, ensure_ascii=False)
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute("""
                INSERT INTO shedcolony_colonist_state
                    (channel_id, citizen_id, hp, job, skills_json, status, state_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(channel_id, citizen_id) DO UPDATE SET
                    hp = excluded.hp,
                    job = excluded.job,
                    skills_json = excluded.skills_json,
                    status = excluded.status,
                    state_json = excluded.state_json,
                    updated_at = CURRENT_TIMESTAMP
            """, (channel_id, citizen_id, d.get("hp"), d.get("job"), skills_json,
                  d.get("status") or "active", state_json))
            await conn.commit()

    async def _world_matches(self, channel_id: int, world_id) -> bool:
        """True если событие из ТЕКУЩЕГО мира канала (или мир неизвестен / старый jar без world_id).
        Для линко-образующих событий (player.linked / colonist.state) mismatch = ОПОЗДАВШЕЕ событие
        старого мира из буфера повторов — его ДРОПАЕМ; переключать мир могут только периодические
        snapshot/capacity живого мира (_check_world_switch)."""
        wid = (world_id or "").strip()
        if not wid:
            return True
        from dependencies import get_db
        async with get_db()._connect() as conn:
            cur = await conn.execute(
                "SELECT world_id FROM shedcolony_world WHERE channel_id=?", (channel_id,))
            row = await cur.fetchone()
        return (not row) or row[0] == wid

    async def _check_world_switch(self, channel_id: int, world_id) -> None:
        """Мир-коллизия (2026-07-03): colony_id=1 в КАЖДОМ мире MineColonies → соло-мир и сервер
        неразличимы, стейт прошлого мира залипал в расширении. Мод шлёт world_id (имя уровня + сид)
        в snapshot/capacity; смена мира → авто-сброс: активные линки → dead, стейт/цели/вакансии →
        wipe → расширение показывает актуальный мир (и «Создать колониста»). Пустой world_id
        (старый jar) — no-op. Fast-path — обычный SELECT; сброс — re-check под BEGIN IMMEDIATE
        (TOCTOU: два события одного мира не должны сбросить дважды)."""
        wid = (world_id or "").strip()
        if not wid:
            return
        from dependencies import get_db
        async with get_db()._connect() as conn:
            cur = await conn.execute(
                "SELECT world_id FROM shedcolony_world WHERE channel_id=?", (channel_id,))
            row = await cur.fetchone()
            if row and row[0] == wid:
                return  # same world — the common case, no write lock taken
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT world_id FROM shedcolony_world WHERE channel_id=?", (channel_id,))
            row = await cur.fetchone()
            if row and row[0] == wid:
                await conn.execute("ROLLBACK")
                return  # another event already switched us — idempotent
            if row:
                await conn.execute(
                    "UPDATE shedcolony_colony_link SET status='dead', died_at=CURRENT_TIMESTAMP "
                    "WHERE channel_id=? AND status='active'", (channel_id,))
                await conn.execute(
                    "DELETE FROM shedcolony_colonist_state WHERE channel_id=?", (channel_id,))
                await conn.execute(
                    "DELETE FROM shedcolony_capacity WHERE channel_id=?", (channel_id,))
                await conn.execute(
                    "DELETE FROM shedcolony_capacity_meta WHERE channel_id=?", (channel_id,))
                await conn.execute(
                    "DELETE FROM shedcolony_targets WHERE channel_id=?", (channel_id,))
                logger.warning("[shedcolony:%s] WORLD SWITCH '%s' → '%s' — links dead + state wiped "
                               "(если это флаппинг каждые ~5с — запущены ДВА мира с одним токеном!)",
                               channel_id, row[0], wid)
            else:
                logger.info("[shedcolony:%s] world id registered: '%s'", channel_id, wid)
            await conn.execute(
                "INSERT INTO shedcolony_world (channel_id, world_id, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "    world_id = excluded.world_id, updated_at = CURRENT_TIMESTAMP",
                (channel_id, wid))
            await conn.commit()

    async def _on_colony_snapshot(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Session-start reconcile against the live colony roster [{id, name}]. Two jobs:
        (1) DEAD-DETECTION — mark any active link whose colonist is GONE from the colony as dead
            (covers a death that never fired player.died → otherwise the link stays active and a
            recycled id collides). (2) NAME CANONICALIZATION — enqueue an internal set_name so every
            linked colonist is named "[MCLink] <viewer>" (rolls back the removed rename feature + tags
            untagged ones). The link table stays the ownership truth (kept correct by player.linked +
            its takeover); names just follow the link."""
        await self._check_world_switch(channel_id, env.data.get("world_id"))
        colonists = env.data.get("colonists") or []
        snap: Dict[str, str] = {}
        for c in colonists:
            cid = str(c.get("id") or "")
            if cid:
                snap[cid] = c.get("name") or ""
        logger.info("[shedcolony:%s] colony.snapshot — %d colonists", channel_id, len(snap))
        if not snap:
            # Мод НЕ шлёт снимок для незагруженной колонии: postSnapshot
            # вызывается только после `targetColony() != null` (ShedReporter.java).
            # Значит пустой ростер = колония ЗАГРУЖЕНА и пуста, а не
            # «ещё не прогрузилась». До 28.08 здесь стоял ранний выход с
            # обратным допущением — и после создания новой колонии четверо
            # зрителей остались привязаны к колонистам, которых нет.
            # Грейс в 60с ниже по-прежнему бережёт только что созданный линк.
            logger.warning(
                "[shedcolony:%s] colony.snapshot пуст — колония загружена и пуста; "
                "сверяю линки против пустого ростера", channel_id)
        import datetime
        from dependencies import get_db
        async with get_db()._connect() as conn:
            cur = await conn.execute(
                "SELECT viewer_id, citizen_id, linked_at FROM shedcolony_colony_link "
                "WHERE channel_id=? AND status='active'", (channel_id,))
            links = [(row[0], row[1], row[2]) for row in await cur.fetchall()]
            tag = "[MCLink] "
            now = datetime.datetime.utcnow()
            for viewer_id, citizen_id, linked_at in links:
                if citizen_id not in snap:
                    # Grace period: if this link was just created (within 60 s), skip dead-marking
                    # so a freshly-linked colonist isn't killed when player.linked and colony.snapshot
                    # arrive in the same burst and the snapshot predates the new link.
                    if linked_at:
                        try:
                            lt = datetime.datetime.fromisoformat(str(linked_at))
                        except ValueError:
                            lt = None
                        if lt and (now - lt).total_seconds() < 60:
                            logger.info(
                                "[shedcolony:%s] reconcile: @%s colonist %s absent from snapshot "
                                "but linked_at=%s (<60s ago) — grace period, skipping dead-mark",
                                channel_id, viewer_id, citizen_id, linked_at)
                            continue
                    await conn.execute(
                        "UPDATE shedcolony_colony_link SET status='dead', died_at=CURRENT_TIMESTAMP "
                        "WHERE channel_id=? AND viewer_id=? AND status='active'",
                        (channel_id, viewer_id))
                    logger.info("[shedcolony:%s] reconcile: @%s colonist %s gone → link dead",
                                channel_id, viewer_id, citizen_id)
                    continue
                want = tag + viewer_id
                if snap.get(citizen_id) != want:
                    await self._enqueue_set_name(conn, channel_id, citizen_id, want)
                    logger.info("[shedcolony:%s] reconcile: canonicalize citizen %s '%s' → '%s'",
                                channel_id, citizen_id, snap.get(citizen_id), want)
            # Гигиена (аудит 2026-07-04): state-строки граждан, которых нет в ростере, копились вечно
            # (и на рециклнутом id мигали ЧУЖИМИ данными до первого свежего colonist.state).
            # Пустой snap дал бы `NOT IN ()` — синтаксическая ошибка SQLite.
            if snap:
                placeholders = ",".join("?" for _ in snap)
                await conn.execute(
                    f"DELETE FROM shedcolony_colonist_state "
                    f"WHERE channel_id=? AND citizen_id NOT IN ({placeholders})",
                    (channel_id, *snap.keys()))
            else:
                await conn.execute(
                    "DELETE FROM shedcolony_colonist_state WHERE channel_id=?",
                    (channel_id,))
            await conn.commit()

    async def _enqueue_set_name(self, conn, channel_id: int, citizen_id: str, name: str) -> None:
        """Queue an INTERNAL colonist.set_name (not viewer-buyable) so the mod renames the colonist to
        its canonical owner name. Skips if one is already queued for this citizen (idempotent)."""
        import uuid
        cur = await conn.execute(
            "SELECT 1 FROM module_actions WHERE channel_id=? AND module_id='shedcolony' "
            "AND type='colonist.set_name' AND status IN ('queued','dispatched') AND data LIKE ? LIMIT 1",
            (channel_id, f'%"citizen_id": "{citizen_id}"%'))
        if await cur.fetchone():
            return
        data = {"citizen_id": citizen_id, "name": name, "internal": True}
        await conn.execute(
            "INSERT INTO module_actions (channel_id, module_id, action_id, type, data, status) "
            "VALUES (?, 'shedcolony', ?, 'colonist.set_name', ?, 'queued')",
            (channel_id, uuid.uuid4().hex, json.dumps(data, ensure_ascii=False)))

    async def _on_colony_capacity(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Снимок свободных слотов колонии (мод шлёт периодически) → slot-availability UI.
        data: {jobs:[{job, free, total}], free_beds, total_beds}. Полная замена снимка."""
        d = env.data
        await self._check_world_switch(channel_id, d.get("world_id"))
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

    async def _on_colony_targets(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Снимок выбираемых целей для пикеров Фазы A/B (мод шлёт периодически). Полная замена.
        data: {researches:[{branch,id,name,state}], buildings:[{pos,type,name,backlog}],
               min_stock:{warehouse,slots_free}}. Храним весь блоб — /capacity отдаёт его фронту."""
        blob = json.dumps(env.data, ensure_ascii=False)
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "INSERT INTO shedcolony_targets (channel_id, data, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "    data = excluded.data, updated_at = CURRENT_TIMESTAMP",
                (channel_id, blob))
            await conn.commit()

    async def _on_colony_catalog(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Мод сверил каталог товаров с реестром предметов СВОЕЙ сборки.

        data: {"missing": [id, ...], "checked": N}. Мы храним результат, а
        `/api/shedcolony/config` вычёркивает отсутствующее — зритель не увидит
        и не купит то, чего в этой сборке нет. Каталог остаётся один, на
        бэкенде; мод только отвечает на вопрос «а это у меня есть?».

        Полная замена: свежий ответ мода отменяет прошлый, иначе снятый товар
        не вернуть после обновления сборки.
        """
        missing = env.data.get("missing")
        checked = env.data.get("checked")
        if not isinstance(missing, list) or not isinstance(checked, int) or checked <= 0:
            return                                   # мусор или старый мод — прошлый ответ важнее
        clean = sorted({str(m) for m in missing if isinstance(m, str) and m})[:200]
        if len(clean) >= checked:
            # Мод не нашёл НИЧЕГО из каталога — так не бывает даже на голой ванили.
            # Скорее сломан сам ответ; гасить весь магазин по нему нельзя.
            logger.warning("[shedcolony] catalog check отброшен: missing=%d при checked=%d "
                        "(channel=%s)", len(clean), checked, channel_id)
            return
        blob = json.dumps({"missing": clean, "checked": checked}, ensure_ascii=False)
        from dependencies import get_db
        async with get_db()._connect() as conn:
            await conn.execute(
                "INSERT INTO shedcolony_catalog_check (channel_id, data, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "    data = excluded.data, updated_at = CURRENT_TIMESTAMP",
                (channel_id, blob))
            await conn.commit()
        if clean:
            logger.info("[shedcolony] сборка канала %s не содержит %d из %d товаров: %s",
                     channel_id, len(clean), checked, ", ".join(clean[:8]))

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
            # BEGIN IMMEDIATE: serialize concurrent action.failed events for the same action_id so the
            # REFUNDED idempotency check + the points credit are one atomic write. Without it a TOCTOU
            # race lets two events both pass the REFUNDED guard before either writes it → double refund.
            await conn.execute("BEGIN IMMEDIATE")
            if not await refund_still_due(conn, "shedcolony", channel_id, action_id, reason):
                await conn.execute("ROLLBACK")
                print(f"[shedcolony:{channel_id}] action.failed {action_id}: игра забрала "
                      f"заявку раньше сторожа — возврата нет")
                return
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
            # Объяснение уходит зрителю ТОЙ ЖЕ транзакцией, что и деньги: падение
            # между ними дало бы либо молчаливый возврат, либо объяснение к
            # невозвращённым крустикам (та же схема, что у Bannerlord).
            # До 2026-09-05 отказа зритель не видел вовсе: приходило только
            # «заявка принята», а потом молча возвращались крустики.
            await add_notice_tx(
                conn, channel_id, username,
                "refund" if price > 0 else "refused",
                describe_refusal(reason), price if price > 0 else 0)
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

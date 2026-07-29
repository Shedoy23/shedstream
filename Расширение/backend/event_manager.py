import asyncio
import logging
import random
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

from config import EVENT_CONFIG, EVENT_ITEMS, EVENT_TYPES


class EventManager:
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

        self.active_event = None
        self.last_event_time = datetime.min

        self.event_pool = 0
        self.event_pool_contributors = {}

        self._current_leader = None
        self._total_extended = 0

        self._lock = asyncio.Lock()
        self._finishing = False

    # =========================
    # Time helpers
    # =========================
    def get_time_left(self):
        if not self.active_event:
            return 0
        return max(0, (self.active_event["end_time"] - datetime.now()).total_seconds())

    def get_top_contributors(self, limit=5):
        items = sorted(
            self.event_pool_contributors.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return [{"username": u, "amount": a} for u, a in items[:limit]]

    def get_top_bidders(self, limit=10):
        if not self.active_event:
            return []
        bids = self.active_event.get("bids", {})
        sorted_bids = sorted(bids.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [{"username": u, "amount": a} for u, a in sorted_bids]

    # =========================
    # Can start
    # =========================
    def can_start_event(self):
        """Синхронная проверка готовности ивента (вызывается внутри лока).

        Порядок важен: сначала проверяем условия (пул), затем КД.
        Если ставить КД первым, он блокирует авто-старт в add_to_pool даже когда
        условия перевыполнены — ивент не запустится до истечения часа.
        """
        ready_reason = None
        # donation-путь удалён 2026-07-02 (B1) — донаты вырезаны Phase 8.F (был dead).
        if self.event_pool >= EVENT_CONFIG["min_points_for_event"]:
            ready_reason = "points"

        if ready_reason is None:
            return False, "not_ready"

        now = datetime.now()
        if (now - self.last_event_time).total_seconds() < EVENT_CONFIG["cooldown_hours"] * 3600:
            return False, "cooldown"

        return True, ready_reason

    # =========================
    # Internal event builder
    # =========================
    def _build_event(self):
        """Создаёт структуру нового ивента и обновляет счётчики пула.
        Вызывается только внутри self._lock.

        Phase 1.E (2026-05-10): рандом-выбор type удалён, остался только
        'auction'. Phase 4 переделает в голосование за действие стримера.
        """
        # Раньше: random.choices(EVENT_TYPES.keys(), weights=...) — выбор
        # между roulette/auction. Сейчас roulette удалён, type всегда 'auction'.
        event_type = "auction"

        prize = random.choices(
            EVENT_ITEMS,
            weights=[i["chance"] for i in EVENT_ITEMS],
        )[0]

        now = datetime.now()

        # M4 follow-up (а): храним channel_id в самом event'е, чтобы end_event
        # (вызываемый из event_watcher_loop в background-контексте) знал куда
        # начислять refunds и приз. Без этого strict resolve_channel_id упадёт.
        from dependencies import resolve_channel_id_or_default
        self.active_event = {
            "id": str(uuid.uuid4())[:8],
            "type": event_type,
            "prize": prize,
            "start_time": now,
            "end_time": now + timedelta(seconds=EVENT_CONFIG["event_duration"]),
            "bids": {},
            "channel_id": resolve_channel_id_or_default(),
        }

        self._current_leader = None
        self._total_extended = 0
        self.event_pool_contributors = {}

        self.event_pool = max(0, self.event_pool - EVENT_CONFIG["min_points_for_event"])
        self.last_event_time = now

        return self.active_event

    # =========================
    # Start
    # =========================
    async def start_event(self):
        """Публичный метод запуска ивента. Уведомление в чат отправляется ВНЕ лока."""
        async with self._lock:
            if self.active_event:
                return None
            event = self._build_event()

        # Уведомляем бота вне лока — не блокируем ставки и пул во время I/O
        try:
            await self.bot.on_event_start(event["type"], event["prize"]["name"])
        except Exception as e:
            print(f"start_event notify error: {e}")

        return event

    # =========================
    # Pool
    # =========================
    # add_to_pool удалён 2026-07-29 вместе с переездом копилки в базу:
    # он растил её ТОЛЬКО в памяти и вызывался отдельным шагом после
    # списания. Замена — charge_and_add_to_pool ниже, одной транзакцией.

    # =========================
    # Копилка в базе (M104, 2026-07-29)
    # =========================
    # До этой правки копилка была полем в памяти процесса: рестарт бэкенда
    # обнулял её, а крустики зрителей уже были списаны — без возврата и без
    # следа. Копилка копится днями до порога в 100 000💎, деплой в середине
    # накопления стирал всё. Теперь истина — в таблице `event_pool`, а поля
    # `event_pool` / `event_pool_contributors` остаются её зеркалом в памяти
    # (их читают can_start_event, топ вкладчиков и страница ивента).

    async def load_pool(self, channel_id=None):
        """Поднять копилку из базы. Зовётся при старте процесса."""
        from dependencies import resolve_channel_id_or_default
        cid = channel_id or resolve_channel_id_or_default()
        try:
            async with self.db._connect() as conn:
                cur = await conn.execute(
                    "SELECT pool FROM event_pool WHERE channel_id=?", (cid,))
                row = await cur.fetchone()
                self.event_pool = int(row[0]) if row else 0
                cur = await conn.execute(
                    "SELECT username, amount FROM event_pool_contributors "
                    "WHERE channel_id=?", (cid,))
                self.event_pool_contributors = {
                    r[0]: int(r[1]) for r in await cur.fetchall()}
        except Exception as e:
            logger.warning("[EVENT-POOL] не удалось поднять копилку: %s", e)
            return
        logger.info("[EVENT-POOL] копилка поднята: %s⭘, вкладчиков %s",
                    self.event_pool, len(self.event_pool_contributors))

    async def charge_and_add_to_pool(self, username, amount, channel_id):
        """Списать крустики и зачесть взнос ОДНОЙ транзакцией.

        Раньше это были два независимых шага: `remove_points` со своим
        соединением и коммитом, потом `add_to_pool` в память. Сбой между ними
        (или рестарт) съедал деньги без взноса.

        Returns (ok: bool, pool: int, reason: str).
        """
        username = (username or "").lower()
        if amount <= 0:
            return False, self.event_pool, "invalid amount"

        event_to_announce = None
        async with self._lock:
            async with self.db._connect() as conn:
                try:
                    await conn.execute("BEGIN IMMEDIATE")
                    cur = await conn.execute(
                        "UPDATE viewers SET points = points - ? "
                        "WHERE channel_id=? AND username=? AND points >= ?",
                        (amount, channel_id, username, amount))
                    if cur.rowcount == 0:
                        await conn.execute("ROLLBACK")
                        return False, self.event_pool, "insufficient points"
                    await conn.execute(
                        "INSERT INTO event_pool (channel_id, pool, updated_at) "
                        "VALUES (?, ?, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(channel_id) DO UPDATE SET "
                        "  pool = pool + excluded.pool, "
                        "  updated_at = CURRENT_TIMESTAMP",
                        (channel_id, amount))
                    await conn.execute(
                        "INSERT INTO event_pool_contributors "
                        "(channel_id, username, amount, updated_at) "
                        "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(channel_id, username) DO UPDATE SET "
                        "  amount = amount + excluded.amount, "
                        "  updated_at = CURRENT_TIMESTAMP",
                        (channel_id, username, amount))
                    cur = await conn.execute(
                        "SELECT pool FROM event_pool WHERE channel_id=?", (channel_id,))
                    new_pool = int((await cur.fetchone())[0])
                    await conn.commit()
                except Exception:
                    try:
                        await conn.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise

            # Память — зеркало базы, а не отдельная правда.
            self.event_pool = new_pool
            self.event_pool_contributors[username] = (
                self.event_pool_contributors.get(username, 0) + amount)

            can_start, _ = self.can_start_event()
            if can_start and not self.active_event:
                event_to_announce = self._build_event()
                await self._persist_pool_reset(channel_id)
            pool_value = self.event_pool

        if event_to_announce is not None:
            try:
                await self.bot.on_event_start(
                    event_to_announce["type"], event_to_announce["prize"]["name"])
            except Exception as e:
                logger.warning("charge_and_add_to_pool notify error: %s", e)

        return True, pool_value, "ok"

    async def _persist_pool_reset(self, channel_id):
        """Записать в базу списание порога из копилки и обнуление вкладчиков.

        Зовётся сразу после `_build_event`, который уже сделал это в памяти.
        """
        try:
            async with self.db._connect() as conn:
                await conn.execute(
                    "UPDATE event_pool SET pool=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE channel_id=?", (self.event_pool, channel_id))
                await conn.execute(
                    "DELETE FROM event_pool_contributors WHERE channel_id=?",
                    (channel_id,))
                await conn.commit()
        except Exception as e:
            logger.warning("[EVENT-POOL] не удалось записать старт ивента: %s", e)

    # =========================
    # Bid
    # =========================
    async def place_bid(self, username, amount):
        # Быстрая проверка существования пользователя ДО захвата лока.
        # Балансовую валидацию делает БД атомарно через remove_points.
        current_points = await self.db.get_points(username)
        if current_points is None:
            return False, "user not found"

        async with self._lock:
            if not self.active_event:
                return False, "no event"

            if amount <= 0:
                return False, "invalid amount"

            if amount < EVENT_CONFIG["min_bid"]:
                return False, "too small"

            if datetime.now() > self.active_event["end_time"]:
                return False, "event ended"

            # Атомарное списание в БД
            deducted = await self.db.remove_points(username, amount)
            if not deducted:
                return False, "insufficient points"

            bids = self.active_event["bids"]
            bids[username] = bids.get(username, 0) + amount

            if self.active_event["type"] == "auction":
                await self._handle_auction_leader(username)

        return True, "ok"

    async def _handle_auction_leader(self, username):
        """Обновляет лидера аукциона и при необходимости продлевает время.
        Вызывается только внутри self._lock."""
        if not self.active_event:
            return

        bids = self.active_event["bids"]
        if not bids:
            return

        new_amount = bids.get(username, 0)
        old_amount = bids.get(self._current_leader, 0) if self._current_leader else -1

        # Меняем лидера только если новая ставка строго больше
        if self._current_leader is not None and new_amount <= old_amount:
            return

        if username == self._current_leader:
            return

        self._current_leader = username

        if not EVENT_CONFIG.get("extend_on_leader_change"):
            return

        time_left = self.get_time_left()
        if time_left < EVENT_CONFIG["extend_threshold"]:
            if self._total_extended < EVENT_CONFIG["extend_max_total"]:
                extend = EVENT_CONFIG["extend_duration"]
                self.active_event["end_time"] += timedelta(seconds=extend)
                self._total_extended += extend

    # =========================
    # End
    # =========================
    async def end_event(self, emit_chat=True):
        async with self._lock:
            if not self.active_event or self._finishing:
                return None, None, None

            self._finishing = True
            event = self.active_event
            self.active_event = None

        try:
            bids = event.get("bids", {})
            # M4 follow-up (а): channel_id хранится в самом event'е (см. _build_event).
            # Передаём явно во все DB-вызовы — иначе background-context end_event
            # (из event_watcher_loop без ContextVar) поймает strict-RuntimeError.
            from dependencies import resolve_channel_id_or_default
            channel_id = event.get("channel_id") or resolve_channel_id_or_default()

            if not bids:
                return None, None, event["prize"]

            winner = None
            message = ""
            total_pool = sum(bids.values())
            participants = len(bids)

            # Phase 1.E (2026-05-10): рулетка-режим вырезан как gambling
            # (§6.2.3 + §6.2.6 — взвешенный рандом по сумме ставок).
            # Остался только аукцион — детерминированный max-bid winner с
            # рефандом проигравшим. В Phase 4 переделается в голосование
            # за действие стримера.
            winner, _ = max(bids.items(), key=lambda x: x[1])
            message = f"аукцион: победил @{winner}"

            # Возвращаем очки проигравшим
            for user, amount in bids.items():
                if user != winner:
                    try:
                        await self.db.add_points(user, amount, channel_id=channel_id)
                    except Exception as e:
                        print(f"refund error {user}: {e}")

            if winner:
                try:
                    # Корректный метод — give_item(username, item_name, quantity=1).
                    # Раньше здесь был несуществующий db.add_item → AttributeError тихо
                    # проглатывался в except, победитель не получал приз.
                    ok = await self.db.give_item(winner, event["prize"]["item_id"], channel_id=channel_id)
                    if not ok:
                        print(f"reward error: item '{event['prize']['item_id']}' not found in items table")
                except Exception as e:
                    print(f"reward error: {e}")

                if emit_chat:
                    try:
                        # Полноценный hook — сам собирает богатое сообщение
                        # в чат (разное для рулетки/аукциона).
                        winner_bid = int(bids.get(winner, 0))
                        await self.bot.on_event_end(
                            winner=winner,
                            event_type=event["type"],
                            prize_name=event["prize"]["name"],
                            winner_bid=winner_bid,
                            total_pool=int(total_pool),
                            participants=participants,
                        )
                    except Exception as e:
                        print(f"winner chat error: {e}")

            return winner, message, event["prize"]

        finally:
            self._finishing = False

    async def finish_event(self):
        """Backward-compatible обёртка над end_event."""
        winner, _, _ = await self.end_event(emit_chat=True)
        return winner

    # =========================
    # Optional watcher
    # =========================
    async def event_watcher_loop(self):
        while True:
            await asyncio.sleep(1)
            if not self.active_event:
                continue

            # ИСПРАВЛЕНО: async with (asyncio.Lock не поддерживает синхронный with)
            async with self._lock:
                should_finish = (
                    self.active_event is not None
                    and datetime.now() >= self.active_event["end_time"]
                )

            if should_finish:
                try:
                    await self.finish_event()
                except Exception as e:
                    logger.error("event watcher error: %s", e, exc_info=True)

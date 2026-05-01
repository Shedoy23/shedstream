# main.py - обновленная версия
import asyncio
from datetime import datetime, timezone
import hashlib
import hmac as _hmac
import logging
import os
import time
import time as _time

# Alias for places that already use _asyncio.create_task(...)
_asyncio = asyncio

# ===== ЛОГИРОВАНИЕ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('rimlink')

import aiohttp
import aiosqlite
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from twitchio.ext import commands as twitch_commands

from bot_core import BotCore
from config import (
    ACTIVITY_CONFIG,
    CACHE_EVICTION_INTERVAL,
    CHANNEL_POINTS_CONFIG,
    DEV_MODE,
    DEV_USERNAME,
    ECONOMY_CONFIG,
    FAMILY_CONFIG,
    LOGIN_ATTEMPT_TTL,
    POINTS_PER_MINUTE,
    QUEST_ORDER,
    QUESTS_CONFIG,
    TWITCH_EXTENSION_SECRET,
    WATCH_TIME_CAP,
    sanitize_username,
    validate_username,
)
from database import Database
from rimworld import router as rimworld_router

load_dotenv(override=True)

# ===== RATE LIMITING =====
from dependencies import check_rate_limit, rate_cleanup_loop as _rate_cleanup_loop  # noqa: E402

# ===== ПРОВЕРКА СТРИМА =====
from dependencies import require_stream_live  # noqa: E402

# ===== JWT ВЕРИФИКАЦИЯ TWITCH EXTENSION =====
from auth import verify_twitch_jwt  # noqa: E402 — после инициализации логгера

app = FastAPI()
pending_commands = []

# RimWorld роуты вынесены в rimworld.py
app.include_router(rimworld_router)

from routes.casino   import router as casino_router
from routes.duel     import router as duel_router
from routes.viewer   import router as viewer_router
from routes.admin    import router as admin_router
from routes.market   import router as market_router
from routes.craft    import router as craft_router
from routes.event    import router as event_router
from routes.promo    import router as promo_router
from routes.marriage import router as marriage_router
from routes.misc     import router as misc_router
app.include_router(casino_router)
app.include_router(duel_router)
app.include_router(viewer_router)
app.include_router(admin_router)
app.include_router(market_router)
app.include_router(craft_router)
app.include_router(event_router)
app.include_router(promo_router)
app.include_router(marriage_router)
app.include_router(misc_router)


# Путь к фронтенду из .env или значение по умолчанию
FRONTEND_PATH = os.getenv("FRONTEND_PATH", "")

# Явные маршруты для файлов расширения — Twitch запрашивает их по точным путям
_EXTENSION_FILES = {
    "/extension.html": "extension.html",
    "/overlay.html":   "overlay.html",
    "/mobile.html":    "mobile.html",
    "/config.html":    "config.html",
    "/viewer.js":      "viewer.js",
    "/viewer.css":     "viewer.css",
    "/market.js":      "market.js",
    "/pawn.js":        "pawn.js",
    "/shop.js":        "shop.js",
    "/casino.js":      "casino.js",
    "/family.js":      "family.js",
    "/duels.js":       "duels.js",
    "/xenotype.js":    "xenotype.js",
}

# Также поддерживаем префикс /frontend/ для совместимости
_EXTENSION_FILES_PREFIXED = {
    "/frontend/extension.html": "extension.html",
    "/frontend/overlay.html":   "overlay.html",
    "/frontend/mobile.html":    "mobile.html",
    "/frontend/config.html":    "config.html",
    "/frontend/viewer.js":      "viewer.js",
    "/frontend/viewer.css":     "viewer.css",
    "/frontend/market.js":      "market.js",
    "/frontend/pawn.js":        "pawn.js",
    "/frontend/shop.js":        "shop.js",
    "/frontend/casino.js":      "casino.js",
    "/frontend/family.js":      "family.js",
    "/frontend/duels.js":       "duels.js",
    "/frontend/xenotype.js":    "xenotype.js",
}

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
}

def _register_extension_routes():
    from fastapi.responses import FileResponse as _FR
    import mimetypes as _mt
    
    # Используем абсолютный путь
    if FRONTEND_PATH:
        base = os.path.abspath(FRONTEND_PATH)
    else:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
    
    # Объединяем оба словаря маршрутов
    all_routes = {**_EXTENSION_FILES, **_EXTENSION_FILES_PREFIXED}
    
    for route, filename in all_routes.items():
        full = os.path.join(base, filename)
        ext  = os.path.splitext(filename)[1]
        mime = _MIME.get(ext, "text/plain")
        exists = os.path.exists(full)
        print(f"  Route: {route} -> {full} (exists: {exists})")
        # closure capture
        def make_handler(path=full, media=mime):
            async def handler():
                if os.path.exists(path):
                    return _FR(path, media_type=media)
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse("File not found", status_code=404)
            return handler
        app.add_api_route(route, make_handler(), methods=["GET"], include_in_schema=False)
    print(f"✅ Extension routes registered (base: {base})")

_register_extension_routes()

# Статические файлы (остальные ресурсы если есть)
if FRONTEND_PATH and os.path.exists(FRONTEND_PATH):
    app.mount("/static", StaticFiles(directory=FRONTEND_PATH), name="static")
    print(f"✅ Frontend папка подключена: {FRONTEND_PATH}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.twitch.tv",
        "https://dashboard.twitch.tv",
        "https://shedoy23.ru",
        "https://supervisor.ext-twitch.tv",
        # OBS Browser Source открывает файлы локально — null origin
        "null",
    ],
    # Twitch Extension хостится на <id>.ext-twitch.tv — wildcard в allow_origins
    # игнорируется Starlette (там точное сравнение строк), нужен regex.
    allow_origin_regex=r"^https://[a-z0-9-]+\.ext-twitch\.tv$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# Security headers на каждый ответ. Не выставляем X-Frame-Options — Twitch
# Extension iframe-ит фронт, нам нужен CSP frame-ancestors вместо запрета.
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # HSTS включает HTTPS на 2 года. На HTTP браузер игнорирует — безопасно.
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    # Кто может iframe-ить наш фронт. Twitch Extension Sandbox = *.ext-twitch.tv,
    # сам Twitch встраивает оверлей в стрим — *.twitch.tv.
    response.headers["Content-Security-Policy"] = (
        "frame-ancestors https://*.twitch.tv https://*.ext-twitch.tv"
    )
    return response

# Инициализация
db = Database("viewers.db")
bot = BotCore(db)

# Регистрируем в dependencies.py чтобы роутеры могли импортировать без цикла
from dependencies import set_db, set_bot  # noqa: E402
set_db(db)
set_bot(bot)

# Callback дропа — пишем в overlay state для оверлея
async def _on_drop_handler(username: str, item_name: str, rarity: str):
    import time as _td
    set_overlay_drop({
        "id": f"{username}-{_td.time():.0f}",
        "username": username,
        "item_name": item_name,
        "rarity": rarity,
        "ts": datetime.now().isoformat(),
    })

bot.on_drop = _on_drop_handler

# Запуск фоновых задач
async def market_expiry_loop():
    """Каждую минуту возвращает предметы из просроченных лотов.

    Для каждого лота — отдельная транзакция BEGIN IMMEDIATE с проверкой rowcount DELETE,
    чтобы не было двойной выдачи при гонке с /api/market/buy (который тоже держит BEGIN IMMEDIATE).
    """
    while True:
        try:
            await asyncio.sleep(60)
            now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            async with db._connect() as conn:
                cursor = await conn.execute(
                    "SELECT id, seller, item_name FROM market_listings WHERE expires_at <= ?", (now,)
                )
                expired = await cursor.fetchall()

            returned = 0
            for lid, seller, item_name in expired:
                async with db._connect() as conn:
                    try:
                        await conn.execute("BEGIN IMMEDIATE")
                        # Сначала удаляем лот — если его уже забрал покупатель, rowcount = 0 и инвентарь не трогаем
                        del_cur = await conn.execute(
                            "DELETE FROM market_listings WHERE id = ? AND expires_at <= ?",
                            (lid, now),
                        )
                        if del_cur.rowcount == 0:
                            await conn.execute("ROLLBACK")
                            continue
                        item_row = await (await conn.execute(
                            "SELECT id FROM items WHERE name = ?", (item_name,)
                        )).fetchone()
                        if item_row:
                            await conn.execute("""
                                INSERT INTO inventory (username, item_id, quantity) VALUES (?, ?, 1)
                                ON CONFLICT(username, item_id) DO UPDATE SET quantity = quantity + 1
                            """, (seller, item_row[0]))
                        await conn.commit()
                        returned += 1
                    except Exception:
                        await conn.execute("ROLLBACK")
                        raise
            if returned:
                print(f"[Market] Возвращено {returned} просроченных лотов")
        except Exception as e:
            print(f"[Market] Ошибка expiry loop: {e}")




from dependencies import set_overlay_drop  # noqa: E402

# ===== СЕМЬЯ =====

async def run_family_income():
    """Фоновая задача: начисляет бонус на семейный счёт когда оба онлайн (таблица marriages)"""
    while True:
        await asyncio.sleep(60)
        try:
            # Начисляем только когда стрим идёт
            if not await bot._is_stream_live():
                continue
            async with db._connect() as conn:
                cursor = await conn.execute("""
                    SELECT username FROM viewers
                    WHERE last_seen > datetime('now', '-10 minutes')
                """)
                online = {r[0] for r in await cursor.fetchall()}

                cursor2 = await conn.execute(
                    "SELECT id, user1, user2 FROM marriages WHERE divorced_at IS NULL")
                for mid, u1, u2 in await cursor2.fetchall():
                    if u1 in online and u2 in online:
                        await conn.execute(
                            "UPDATE marriages SET family_balance = family_balance + ? WHERE id = ?",
                            (FAMILY_CONFIG['bonus_per_min'], mid))
                await conn.commit()
        except Exception as e:
            print(f"family_income error: {e}")


from routes.misc import get_twitch_app_token  # noqa: E402


async def run_migrations():
    """Применяем миграции БД"""
    async with aiosqlite.connect(db.db_path) as conn:
        # Добавляем hediff_type если нет
        try:
            await conn.execute("ALTER TABLE rimworld_pawn_hediffs ADD COLUMN hediff_type TEXT DEFAULT 'injury'")
            await conn.commit()
            print("✅ Migration: hediff_type добавлен")
        except Exception:
            pass  # Уже есть

        # Миграция: точные данные имплантов (def_name, part_def, is_paired, is_left)
        for col, ddl in [
            ("hediff_def", "TEXT DEFAULT ''"),
            ("part_def",   "TEXT DEFAULT ''"),
            ("is_paired",  "INTEGER DEFAULT 0"),
            ("is_left",    "INTEGER"),          # NULL = непарный, 0 = правый, 1 = левый
        ]:
            try:
                await conn.execute(f"ALTER TABLE rimworld_pawn_hediffs ADD COLUMN {col} {ddl}")
                await conn.commit()
                print(f"✅ Migration: {col} добавлен в rimworld_pawn_hediffs")
            except Exception:
                pass  # Уже есть
        # Добавляем is_disabled в rimworld_pawn_skills если нет
        try:
            await conn.execute("ALTER TABLE rimworld_pawn_skills ADD COLUMN is_disabled INTEGER DEFAULT 0")
            await conn.commit()
            print("✅ Migration: is_disabled добавлен в rimworld_pawn_skills")
        except Exception:
            pass  # Уже есть

        # Таблица персистентных команд RimWorld
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS rimworld_pending_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cmd_id TEXT UNIQUE,
                cmd_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Промокоды
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS promocodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                points INTEGER DEFAULT 0,
                item_def TEXT DEFAULT NULL,
                item_name TEXT DEFAULT NULL,
                max_uses INTEGER DEFAULT 1,
                uses INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS promo_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                username TEXT NOT NULL,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(code, username)
            )
        """)

        # Браки (единственная таблица семей — families удалена)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS marriages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1 TEXT NOT NULL,
                user2 TEXT NOT NULL,
                family_balance INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                divorced_at TIMESTAMP DEFAULT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS marriage_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user TEXT NOT NULL,
                to_user TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


        # Таблица выданных наград за стрики просмотров
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS streak_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                streak_count INTEGER NOT NULL,
                diamonds_given INTEGER NOT NULL,
                given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(username, streak_count)
            )
        """)

        # Лог обмена channel points → алмазы
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_points_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                twitch_redemption_id TEXT UNIQUE,
                reward_title TEXT NOT NULL,
                channel_points_spent INTEGER NOT NULL,
                diamonds_given INTEGER NOT NULL,
                redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await conn.commit()
        print("✅ Migration: streak_rewards + channel_points_log созданы")

        # Миграция: исправить русские skill_name → английские defName
        # (до фикса бэкенд сохранял label вместо def_name)
        # Исправлено: используем CASE WHEN для безопасного обновления больших данных
        _skill_name_map = {
            "Стрельба": "Shooting", "Ближний бой": "Melee",
            "Строительство": "Construction", "Добыча": "Mining",
            "Готовка": "Cooking", "Растениеводство": "Plants",
            "Животноводство": "Animals", "Ремесло": "Crafting",
            "Искусство": "Artistic", "Медицина": "Medicine",
            "Социальность": "Social", "Интеллект": "Intellectual",
        }
        for _rus, _eng in _skill_name_map.items():
            try:
                await conn.execute(
                    """UPDATE rimworld_pawn_skills
                       SET skill_name = CASE skill_name
                           WHEN ? THEN ?
                       END WHERE skill_name = ?""",
                    (_rus, _eng, _rus))
            except Exception:
                pass
        await conn.commit()
        print("✅ Migration: skill_name локализация исправлена")
        print("✅ Migrations complete")


# ===== TWITCH IRC БОТ (отслеживание чата) =====

class TwitchChatBot(twitch_commands.Bot):
    def __init__(self):
        token = os.getenv('TWITCH_OAUTH_TOKEN', '')
        channel = os.getenv('TWITCH_CHANNEL_NAME', '').lower().strip()
        if not token or not channel:
            print("TWITCH_OAUTH_TOKEN или TWITCH_CHANNEL_NAME не заданы — IRC бот не запустится")
            return
        super().__init__(token=token, prefix='!', initial_channels=[channel])
        self._channel = channel
        print(f"🎮 TwitchChatBot инициализирован для канала: {channel}")

    async def event_ready(self):
        print(f"✅ IRC бот подключён как {self.nick} к #{self._channel}")
        # Передаём ссылку на себя в BotCore чтобы send_message работал
        bot.twitch_bot = self
        # Флашим сообщения которые накопились пока IRC подключался
        # (иначе end_event-оповещения из event_watcher_loop, стартовавшего
        # раньше IRC, уходили в "[CHAT LOG]" и не попадали в Twitch).
        try:
            await bot.flush_pending_chat()
        except Exception as e:
            print(f"flush_pending_chat error: {e}")

    async def send_message(self, message: str):
        """Отправить сообщение в канал через twitchio."""
        try:
            channel = self.get_channel(self._channel)
            if channel:
                await channel.send(message)
                print(f"📢 [CHAT] {message}")
            else:
                print(f"Канал {self._channel} не найден — сообщение не отправлено")
        except Exception as e:
            print(f"send_message error: {e}")

    async def event_message(self, message):
        if message.echo:
            return
        username = message.author.name.lower() if message.author else None
        if not username:
            return
        text = message.content or ''
        # Сбрасываем AFK — зритель написал в чат
        bot.update_viewer_chat(username)
        try:
            async with db._connect() as conn:
                await conn.execute("""
                    INSERT INTO viewers (username, last_seen, is_afk)
                    VALUES (?, datetime('now'), 0)
                    ON CONFLICT(username) DO UPDATE SET
                        last_seen = datetime('now'), is_afk = 0
                """, (username,))
                await conn.execute("""
                    INSERT INTO chat_stats (username, message_length, message_text)
                    VALUES (?, ?, ?)
                """, (username, len(text), ''))
                await conn.commit()
            # Бонус очки за сообщение
            bonus = min(len(text) // 10, 10)
            if bonus > 0:
                await db.add_points(username, bonus)
            # Обновляем чат-квесты
            await bot._update_quest_progress(username, 'chat_messages_10', 1)
            await bot._update_quest_progress(username, 'chat_messages_25', 1)
            await bot._update_quest_progress(username, 'chat_messages_50', 1)
            await bot._update_quest_progress(username, 'chat_messages_100', 1)
        except Exception as e:
            print(f"IRC chat error: {e}")

    async def event_raw_data(self, data: str):
        """Ловим USERNOTICE — стрики просмотров и другие системные события."""
        try:
            if 'USERNOTICE' not in data:
                return
            print(f"📨 USERNOTICE raw: {data[:400]}")
            # Парсим теги из IRC строки
            tags = {}
            if data.startswith('@'):
                tag_str = data[1:data.index(' ')]
                for part in tag_str.split(';'):
                    if '=' in part:
                        k, v = part.split('=', 1)
                        tags[k] = v.replace('\\s', ' ').replace('\\:', ':')

            msg_id = tags.get('msg-id', '')
            if msg_id != 'viewership-milestone':
                return

            # login — ник зрителя который получил milestone
            username = tags.get('login', '').lower()
            # msg-param-streak-months — количество стримов подряд
            streak = int(tags.get('msg-param-streak-months', 0))

            if not username or streak <= 0:
                return

            print(f"🔥 Milestone: @{username} смотрит {streak} стримов подряд!")

            # Ищем подходящую награду (берём наибольшую не превышающую streak)
            from config import STREAK_REWARDS
            reward = 0
            matched_streak = 0
            for threshold in sorted(STREAK_REWARDS.keys()):
                if streak >= threshold:
                    reward = STREAK_REWARDS[threshold]
                    matched_streak = threshold

            if reward <= 0:
                return

            # Проверяем что уже не выдавали эту награду за этот стрик (BEGIN IMMEDIATE — атомарно)
            async with db._connect() as conn:
                await conn.execute("BEGIN IMMEDIATE")
                cursor = await conn.execute(
                    "SELECT id FROM streak_rewards WHERE username=? AND streak_count=?",
                    (username, matched_streak)
                )
                already_given = await cursor.fetchone()
                if already_given:
                    await conn.execute("ROLLBACK")
                    print(f"⏭️ Награда за стрик {matched_streak} уже выдана @{username}")
                    return
                await conn.execute(
                    "INSERT INTO streak_rewards (username, streak_count, diamonds_given) VALUES (?,?,?)",
                    (username, matched_streak, reward)
                )
                await conn.commit()

            await db.add_points(username, reward)
            print(f"🎁 @{username} получил {reward}💎 за {matched_streak} стримов подряд!")

            # Поздравление в чат
            try:
                await bot.send_message(
                    f"🔥 @{username} смотрит стрим {streak} раз подряд! "
                    f"Получает {reward}💎 за преданность! PogChamp"
                )
            except Exception:
                pass

        except Exception as e:
            print(f"event_raw_data error: {e}")

_twitch_chat_bot = None

# ===== EVENTSUB: CHANNEL POINTS =====

async def register_eventsub_channel_points():
    """Подписываемся на channel.channel_points_custom_reward_redemption.add через EventSub.
    Webhook EventSub требует App Access Token (client credentials).
    """
    if not CHANNEL_POINTS_CONFIG.get('enabled'):
        return
    broadcaster_id = CHANNEL_POINTS_CONFIG.get('broadcaster_id', '')
    if not broadcaster_id:
        print("EventSub: TWITCH_BROADCASTER_ID не задан в .env — channel points не работают")
        return

    client_id    = os.getenv('TWITCH_CLIENT_ID', '')
    callback_url = os.getenv('EVENTSUB_CALLBACK_URL', '')
    secret       = CHANNEL_POINTS_CONFIG['eventsub_secret']

    if not callback_url:
        print("EventSub: EVENTSUB_CALLBACK_URL не задан в .env")
        return

    try:
        app_token = await get_twitch_app_token()
        headers = {"Client-ID": client_id, "Authorization": f"Bearer {app_token}"}
        print(f"🔍 EventSub: регистрация, broadcaster_id={broadcaster_id}, client_id={client_id[:8]}...")

        async with aiohttp.ClientSession() as session:
            # Проверяем — нет ли уже активной подписки
            async with session.get(
                "https://api.twitch.tv/helix/eventsub/subscriptions",
                headers=headers
            ) as r:
                existing = await r.json()
                if r.status not in (200, 202):
                    print(f"EventSub: ошибка получения подписок ({r.status}): {existing}")
                    return
                for sub in existing.get('data', []):
                    if (sub['type'] == 'channel.channel_points_custom_reward_redemption.add'
                            and sub['condition'].get('broadcaster_user_id') == broadcaster_id
                            and sub['status'] == 'enabled'):
                        print("✅ EventSub: подписка на channel points уже активна")
                        return

            # Регистрируем подписку
            async with session.post(
                "https://api.twitch.tv/helix/eventsub/subscriptions",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "type": "channel.channel_points_custom_reward_redemption.add",
                    "version": "1",
                    "condition": {"broadcaster_user_id": broadcaster_id},
                    "transport": {
                        "method": "webhook",
                        "callback": callback_url,
                        "secret": secret
                    }
                }
            ) as r:
                resp = await r.json()
                if r.status in (200, 202):
                    print("✅ EventSub: подписка на channel points зарегистрирована, ждём верификацию...")
                else:
                    print(f"EventSub: ошибка регистрации: {resp}")
    except Exception as e:
        print(f"EventSub register error: {e}")


@app.post("/eventsub/channel-points")
async def eventsub_channel_points(request: Request):
    """Вебхук от Twitch EventSub — срабатывает когда зритель тратит channel points."""
    import json as _json
    body_bytes = await request.body()

    msg_id        = request.headers.get("Twitch-Eventsub-Message-Id", "")
    msg_timestamp = request.headers.get("Twitch-Eventsub-Message-Timestamp", "")
    msg_signature = request.headers.get("Twitch-Eventsub-Message-Signature", "")
    msg_type      = request.headers.get("Twitch-Eventsub-Message-Type", "")
    secret        = CHANNEL_POINTS_CONFIG['eventsub_secret'].encode()

    hmac_msg = (msg_id + msg_timestamp).encode() + body_bytes
    expected_sig = "sha256=" + _hmac.new(secret, hmac_msg, hashlib.sha256).hexdigest()

    if not _hmac.compare_digest(expected_sig, msg_signature):
        print(f"EventSub: неверная подпись! expected={expected_sig[:30]} got={msg_signature[:30]}")
        return JSONResponse({"error": "invalid signature"}, status_code=403)

    # Replay-protection: Twitch шлёт ISO-таймстамп, отказываем сообщениям старше 10 мин.
    # Дедуп по redemption_id защищает только пока БД жива; timestamp-window нужен
    # для случая «БД пересоздана, старая валидная подпись переиграна».
    try:
        msg_dt = datetime.fromisoformat(msg_timestamp.replace('Z', '+00:00'))
        age_sec = abs(_time.time() - msg_dt.timestamp())
        if age_sec > 600:
            print(f"EventSub: timestamp out of window ({int(age_sec)}s)")
            return JSONResponse({"error": "timestamp out of window"}, status_code=403)
    except (ValueError, TypeError) as e:
        print(f"EventSub: bad timestamp '{msg_timestamp}': {e}")
        return JSONResponse({"error": "bad timestamp"}, status_code=400)

    # Парсим тело из body_bytes (request.json() повторно не читает стрим)
    data = _json.loads(body_bytes)

    # Twitch требует подтвердить подписку при первом запросе
    if msg_type == "webhook_callback_verification":
        challenge = data.get("challenge", "")
        print("✅ EventSub: верификация подписки, отвечаем challenge")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=challenge)

    if msg_type == "notification":
        event = data.get("event", {})
        username    = event.get("user_login", "").lower()
        reward_title = event.get("reward", {}).get("title", "")
        redemption_id = event.get("id", "")

        rewards_cfg = CHANNEL_POINTS_CONFIG.get('rewards', {})
        reward_cfg  = rewards_cfg.get(reward_title)

        if not reward_cfg:
            # Название награды не в конфиге — игнорируем
            return JSONResponse({"status": "ignored"})

        diamonds = reward_cfg['diamonds']

        # Проверяем дублирование по redemption_id
        async with db._connect() as conn:
            cursor = await conn.execute(
                "SELECT id FROM channel_points_log WHERE twitch_redemption_id=?",
                (redemption_id,)
            )
            if await cursor.fetchone():
                return JSONResponse({"status": "duplicate"})

            await conn.execute(
                """INSERT INTO channel_points_log
                   (username, twitch_redemption_id, reward_title, channel_points_spent, diamonds_given)
                   VALUES (?,?,?,?,?)""",
                (username, redemption_id, reward_title,
                 reward_cfg['channel_points_cost'], diamonds)
            )
            await conn.commit()

        await db.add_points(username, diamonds)
        print(f"💜 @{username} обменял channel points '{reward_title}' → +{diamonds}💎")

        try:
            await bot.send_message(
                f"💜 @{username} обменял баллы канала на {diamonds}💎! "
                f"Спасибо за поддержку! monkaHmm"
            )
        except Exception:
            pass

    return JSONResponse({"status": "ok"})


async def start_twitch_bot():
    global _twitch_chat_bot
    # Retry loop — пробуем подключиться с паузами при ошибке
    while True:
        try:
            _twitch_chat_bot = TwitchChatBot()
            if not hasattr(_twitch_chat_bot, '_channel'):
                print("IRC бот: токен или канал не заданы")
                return
            # connect() работает в текущем event loop (в отличие от start())
            await _twitch_chat_bot.connect()
            print("✅ IRC бот подключён")
            return
        except Exception as e:
            print(f"IRC бот не запустился: {e} — повтор через 30 сек")
            await asyncio.sleep(30)


# Таблицы для очистки тестовых аккаунтов
_CLEANUP_TABLES = ["viewers", "rimworld_pawns", "quests", "chat_stats", "activity_stats", "inventory"]

async def cleanup_test_accounts():
    """Удаляем тестовые аккаунты созданные в ходе пентеста"""
    test_users = ['Ethanenak', 'ethanenak', 'Sosi', 'sosi', 'Pisun', 'pisun',
                  'Chlen', 'chlen', 'testuser',
                  'Pedka_Ethanenka', 'Pedka_Sosi', 'HACKED_PAWN']
    async with db._connect() as conn:
        for u in test_users:
            cursor = await conn.execute("SELECT username FROM viewers WHERE username = ?", (u,))
            if await cursor.fetchone():
                for table in _CLEANUP_TABLES:
                    await conn.execute(f"DELETE FROM {table} WHERE username = ?", (u,))
                print(f"🗑️ Удалён тестовый аккаунт: {u}")
        await conn.commit()
    print("✅ Тестовые аккаунты очищены")

# ===== ЗАПУСК =====
@app.on_event("startup")
async def on_startup():
    # Инициализация БД
    try:
        await db.init_pool()   # сначала пул соединений
        await db.init_tables()
        await run_migrations()
        await cleanup_test_accounts()
    except Exception as e:
        print(f"❌ Критическая ошибка при инициализации БД: {e}")
        raise  # Падаем явно — не скрываем проблему
    # Служебные фоновые задачи
    asyncio.create_task(_rate_cleanup_loop())
    # Фоновые задачи бота
    asyncio.create_task(bot.reward_points_loop())
    asyncio.create_task(bot.drop_loop())
    asyncio.create_task(market_expiry_loop())
    # Автозавершение рулекционов по таймеру (иначе ивент висит
    # до следующего опроса /api/event/status — и чат-оповещение
    # о победителе не уходит).
    asyncio.create_task(bot.event_manager.event_watcher_loop())
    # IRC бот и семейный доход
    asyncio.create_task(start_twitch_bot())
    asyncio.create_task(bot.auto_message_loop())
    # Safety-net для сообщений, поставленных в очередь до коннекта IRC:
    # event_ready() флашит один раз, но если что-то поставилось позже (гонка
    # или transient disconnect), этот цикл каждые 15с добивает хвост.
    asyncio.create_task(bot.pending_chat_flush_loop())
    asyncio.create_task(run_family_income())
    asyncio.create_task(register_eventsub_channel_points())
    # Сезоны дуэлей — проверка при старте + восстановление pending
    from routes.duel import check_season_end as _duel_season_check
    from routes.duel import load_pending_duels as _load_pending_duels
    asyncio.create_task(_duel_season_check())
    try:
        await _load_pending_duels()
    except Exception as e:
        print(f"⚠️ Не удалось загрузить pending-дуэли: {e}")
    print("✅ Сервер запущен")

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_migrations())
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

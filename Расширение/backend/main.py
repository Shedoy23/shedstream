# main.py - обновленная версия
import asyncio
from datetime import datetime, timezone
import logging
import os
import time
import time as _time
from typing import Optional

# Alias for places that already use _asyncio.create_task(...)
_asyncio = asyncio

# ===== ЛОГИРОВАНИЕ =====
# Sprint 5.33 PHASE1-3 (2026-05-28): switched к structured logging.
# Default text format (dev-friendly). Production: set LOG_FORMAT=json для
# Loki/ELK/Datadog ingestion. Level via LOG_LEVEL.
from logging_setup import setup_logging
setup_logging()
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
    # FAMILY_CONFIG удалён 2026-05-10 (Phase 1.G — financial pool removed)
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

app = FastAPI()
pending_commands = []

# RimWorld роуты вынесены в rimworld.py
app.include_router(rimworld_router)

from routes.duel     import router as duel_router
from routes.viewer   import router as viewer_router
from routes.admin    import router as admin_router
# market_router удалён 2026-05-10 — Phase 1.C compliance rework (P2P trade items, §6.2.8)
# craft_router удалён 2026-05-10 — Phase 1.B compliance rework (3/3 gambling: §6.2.4 + §5.3)
from routes.event    import router as event_router
from routes.promo    import router as promo_router
from routes.marriage import router as marriage_router
from routes.misc     import router as misc_router
from routes.streamer   import router as streamer_router
from routes.module_api import router as module_api_router
from routes.cases      import router as cases_router  # Phase 2 (2026-05-11)
from routes.match      import router as match_router  # Phase 5.0 (2026-05-11)
from routes.tictactoe  import router as tictactoe_router  # Phase 5.1 (2026-05-11)
from routes.dice       import router as dice_router       # Phase 5.2 (2026-05-11)
from routes.guilds     import router as guilds_router     # Phase 3 (2026-05-11)
from routes.voting     import router as voting_router     # Phase 4 (2026-05-11)
from routes.pets       import router as pets_router       # Phase 7 (2026-05-12)
from routes.tts        import router as tts_router        # Sprint 5.23 (2026-05-21)
from routes.rps        import router as rps_router        # Sprint 5.24b (2026-05-21)
from routes.bannerlord  import router as bannerlord_router # Sprint 1.3 (2026-05-15)
from routes.shedcolony  import router as shedcolony_router # ShedColony viewer endpoints (2026-06-25)
from routes.bannerlord_achievements import router as bannerlord_achievements_router # Sprint 5.29
from routes.bannerlord_custom_items import router as bannerlord_custom_items_router # Sprint 5.29
from routes.bannerlord_auctions import router as bannerlord_auctions_router  # Sprint 5.29 phase B
from routes.bannerlord_family import router as bannerlord_family_router       # Sprint 5.33 BLT-parity FAM
from routes.bannerlord_vassals import router as bannerlord_vassals_router     # Sprint 5.33 BLT-parity VAS
from routes.bannerlord_party_orders import router as bannerlord_party_orders_router  # Sprint 5.33 BLT-parity SIEGE
from routes.bannerlord_diplomacy import router as bannerlord_diplomacy_router  # Sprint 5.33 BLT-parity DIPLO
from routes.bannerlord_workshops import router as bannerlord_workshops_router  # Sprint 5.33 BLT-parity SHOP
from routes.bannerlord_fiefs import router as bannerlord_fiefs_router  # Sprint 5.33 BLT-parity FIEF
from routes.bannerlord_caravans import router as bannerlord_caravans_router  # Sprint 5.33 BLT-parity CARAVAN
from routes.bannerlord_settlements import router as bannerlord_settlements_router  # Sprint 5.33 CATALOG-2
from routes.bannerlord_admin import router as bannerlord_admin_router  # Sprint 5.33 RESET-1 — streamer admin tools
from routes.bannerlord_boosty import router as bannerlord_boosty_router  # Sprint 5.31 #45
from routes.dev_login   import router as dev_login_router  # /dev test page (2026-05-16)
# casino_router удалён 2026-05-10 — Phase 1.A compliance rework (см. COMPLIANCE_REWORK_PLAN.md)
app.include_router(duel_router)
app.include_router(viewer_router)
app.include_router(admin_router)
# market_router удалён 2026-05-10 (Phase 1.C compliance rework)
# craft_router удалён 2026-05-10 (Phase 1.B compliance rework)
app.include_router(event_router)
app.include_router(promo_router)
app.include_router(marriage_router)
app.include_router(misc_router)
app.include_router(streamer_router)    # M4.3: OAuth flow для регистрации стримеров
app.include_router(module_api_router)  # Этап 3: Module API (handshake + module registry)
app.include_router(cases_router)       # Phase 2 (2026-05-11): cases system
app.include_router(match_router)       # Phase 5.0 (2026-05-11): matchmaking base
app.include_router(tictactoe_router)   # Phase 5.1 (2026-05-11): TicTacToe MVP
app.include_router(dice_router)        # Phase 5.2 (2026-05-11): Dice match
app.include_router(guilds_router)      # Phase 3 (2026-05-11): Guilds base
app.include_router(voting_router)      # Phase 4 (2026-05-11): Voting events
app.include_router(pets_router)        # Phase 7 (2026-05-12): Pets MVP (cross-channel)
app.include_router(tts_router)         # Sprint 5.23 (2026-05-21): TTS «Озвучить сообщение»
app.include_router(rps_router)         # Sprint 5.24b (2026-05-21): RPS bo3 matchmade
app.include_router(bannerlord_router)  # Sprint 1.3 (2026-05-15): Bannerlord viewer endpoints
app.include_router(shedcolony_router)  # ShedColony viewer endpoints (buy / my-colonist / capacity)
app.include_router(bannerlord_achievements_router)  # Sprint 5.29 BLT-parity #5
app.include_router(bannerlord_custom_items_router)  # Sprint 5.29 BLT-parity #6
app.include_router(bannerlord_auctions_router)  # Sprint 5.29 BLT-parity #6 phase B
app.include_router(bannerlord_family_router)    # Sprint 5.33 BLT-parity FAM — marriage proposals
app.include_router(bannerlord_vassals_router)   # Sprint 5.33 BLT-parity VAS — vassal sub-clans
app.include_router(bannerlord_party_orders_router)  # Sprint 5.33 BLT-parity SIEGE — party orders
app.include_router(bannerlord_diplomacy_router)  # Sprint 5.33 BLT-parity DIPLO — kingdom politics + ransom
app.include_router(bannerlord_workshops_router)  # Sprint 5.33 BLT-parity SHOP — workshops passive income
app.include_router(bannerlord_fiefs_router)  # Sprint 5.33 BLT-parity FIEF — fief tribute passive income
app.include_router(bannerlord_caravans_router)  # Sprint 5.33 BLT-parity CARAVAN — mobile passive income + rescue
app.include_router(bannerlord_settlements_router)  # Sprint 5.33 CATALOG-2 — live engine settlements dropdown
app.include_router(bannerlord_admin_router)  # Sprint 5.33 RESET-1 — streamer admin tools
app.include_router(bannerlord_boosty_router)    # Sprint 5.31 #45 — Boosty subs
app.include_router(dev_login_router)   # 2026-05-16: /dev OAuth test page

# Phase A (2026-05-16): EventSub generic router (/eventsub + legacy alias
# /eventsub/channel-points). Заменил inline-обработчик и старую
# register_eventsub_channel_points функцию.
from eventsub import router as eventsub_router  # noqa: E402
app.include_router(eventsub_router)


# Путь к фронтенду из .env или значение по умолчанию
FRONTEND_PATH = os.getenv("FRONTEND_PATH", "")

# Явные маршруты для файлов расширения — Twitch запрашивает их по точным путям
_EXTENSION_FILES = {
    "/":               "index.html",    # публичный лендинг shedoy23.ru (2026-07-02)
    "/index.html":     "index.html",
    "/extension.html": "extension.html",
    "/overlay.html":   "overlay.html",
    "/mobile.html":    "mobile.html",
    "/config.html":    "config.html",
    "/config.js":      "config.js",
    "/viewer.js":      "viewer.js",
    "/viewer.css":     "viewer.css",
    "/pawn.js":        "pawn.js",
    "/shop.js":        "shop.js",
    "/family.js":      "family.js",
    "/duels.js":       "duels.js",
    "/xenotype.js":    "xenotype.js",
    "/cases.js":       "cases.js",
    "/tictactoe.js":   "tictactoe.js",
    "/dice.js":        "dice.js",
    "/guilds.js":      "guilds.js",
    "/voting.js":      "voting.js",
    "/pets.js":        "pets.js",
    "/pet-stage.js":   "pet-stage.js",  # Sprint 5.21: shared SVG creature renderer
    "/realtime.js":    "realtime.js",   # Phase C: PubSub realtime bus
    "/privacy.html":   "privacy.html",  # Twitch submission: Privacy Policy URL
    "/terms.html":     "terms.html",    # Twitch submission: Terms of Service URL
}

# Также поддерживаем префикс /frontend/ для совместимости
_EXTENSION_FILES_PREFIXED = {
    "/frontend/extension.html": "extension.html",
    "/frontend/overlay.html":   "overlay.html",
    "/frontend/mobile.html":    "mobile.html",
    "/frontend/config.html":    "config.html",
    "/frontend/config.js":      "config.js",
    "/frontend/viewer.js":      "viewer.js",
    "/frontend/viewer.css":     "viewer.css",
    "/frontend/pawn.js":        "pawn.js",
    "/frontend/shop.js":        "shop.js",
    "/frontend/family.js":      "family.js",
    "/frontend/duels.js":       "duels.js",
    "/frontend/xenotype.js":    "xenotype.js",
    "/frontend/cases.js":       "cases.js",
    "/frontend/tictactoe.js":   "tictactoe.js",
    "/frontend/dice.js":        "dice.js",
    "/frontend/guilds.js":      "guilds.js",
    "/frontend/voting.js":      "voting.js",
    "/frontend/pets.js":        "pets.js",
    "/frontend/pet-stage.js":   "pet-stage.js",  # Sprint 5.21
    "/frontend/realtime.js":    "realtime.js",   # Phase C
    "/frontend/privacy.html":   "privacy.html",
    "/frontend/terms.html":     "terms.html",
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

    # ROADMAP 2.4: split-модули viewer-*.js (viewer-rimworld.js / viewer-bannerlord.js)
    # авто-регистрируем из папки — чтобы новый кусок сплита не давал 404 без ручного
    # добавления в словарь (этот класс бага уже один раз поймали).
    import glob as _glob
    for _fp in _glob.glob(os.path.join(base, "viewer-*.js")):
        _fn = os.path.basename(_fp)
        all_routes.setdefault(f"/{_fn}", _fn)
        all_routes.setdefault(f"/frontend/{_fn}", _fn)

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
    # Раздача модов + install-инструкций (2026-07-02): /downloads/<game>/<file>
    _downloads_path = os.path.join(FRONTEND_PATH, "downloads")
    if os.path.isdir(_downloads_path):
        app.mount("/downloads", StaticFiles(directory=_downloads_path), name="downloads")
        print(f"✅ Downloads подключены: {_downloads_path}")
    # Sprint 5.28: pet-assets/ mount для PixelLab PNG-спрайтов character'а
    # (kimono + underwear × 8 directions). pet-stage.js загружает их по
    # относительному пути "pet-assets/v2/{variant}/{direction}.png".
    _pet_assets_path = os.path.join(FRONTEND_PATH, "pet-assets")
    if os.path.exists(_pet_assets_path):
        app.mount("/pet-assets", StaticFiles(directory=_pet_assets_path), name="pet-assets")
        # Также под /frontend/ — extension.html/JS отдаются по ОБОИМ путям (root и
        # /frontend/), а Local Test "Base URI" может быть с хвостом /frontend/. Без
        # этого зеркала pet-assets 404'ились бы по префиксу → синий «?» вместо спрайта.
        app.mount("/frontend/pet-assets", StaticFiles(directory=_pet_assets_path), name="pet-assets-frontend")
        print(f"✅ Pet-assets mounted: {_pet_assets_path} (root + /frontend/)")
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
    # Public-gate (2026-07-02): было "*". Фронт шлёт только Content-Type +
    # X-Twitch-JWT; Authorization на будущее. Явный список — меньше поверхность.
    allow_headers=["Authorization", "Content-Type", "X-Twitch-JWT", "X-Requested-With"],
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
    # Public-gate (2026-07-02): расширению не нужны камера/микрофон/гео —
    # запрещаем явно (defence-in-depth; браузер откажет любому такому вызову).
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

# Инициализация
# DB_PATH — путь к базе. По умолчанию «viewers.db» рядом с кодом, то есть на
# проде ничего не меняется (там переменная не задана — проверено 2026-07-26).
# Нужна локальной разработке: позволяет держать копию базы ВНЕ репозитория.
# Локальная база рядом с кодом — ровно та конфигурация, которая 2026-06-25
# положила прод: локальный журнал (-wal) уехал в архив деплоя и затёр
# прод-журнал. Починили исключением в deploy.ps1, но защита держится на одной
# строке в одном скрипте; база снаружи — вторая линия, от неё независимая.
#
# Имя именно DB_PATH, потому что оно УЖЕ существовало (backup_loop.py, db_pool.py).
# Я сперва завёл своё, SHEDSTREAM_DB, не посмотрев, что есть — и получил две
# переменные для одного пути: main.py читал одну, фоновые бэкапы другую, и
# локальный запуск копировал НЕ ТУ базу. Тот же класс, что мы весь день чиним.
db = Database(os.getenv("DB_PATH", "viewers.db"))
bot = BotCore(db)

# Регистрируем в dependencies.py чтобы роутеры могли импортировать без цикла
from dependencies import set_db, set_bot  # noqa: E402
set_db(db)
set_bot(bot)


# ROADMAP 2.6 — лёгкий health-check для внешнего мониторинга (UptimeRobot/cron).
# Без auth, без тяжёлых запросов. 200 = процесс жив + БД отвечает; 503 = БД
# недоступна; полное падение процесса → монитор увидит connection refused/timeout.
@app.get("/health", include_in_schema=False)
@app.head("/health", include_in_schema=False)
async def health():
    db_ok = False
    try:
        async with db._connect() as conn:
            await conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    return JSONResponse(
        {"status": "ok" if db_ok else "degraded", "db": "ok" if db_ok else "fail"},
        status_code=200 if db_ok else 503,
    )

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

# market_expiry_loop удалён 2026-05-10 (Phase 1.C compliance rework — рынок P2P
# вырезан как §6.2.8 + 2026-Bits-tightening: items specified by users + off-platform
# value exchange). См. COMPLIANCE_REWORK_PLAN.md §4 Phase 1.



from dependencies import set_overlay_drop  # noqa: E402

# ===== СЕМЬЯ =====
# run_family_income() удалён 2026-05-10 (Phase 1.G compliance rework).
# Раньше начислял +15💎/мин на family_balance когда оба супруга онлайн —
# это shared currency pool с P2P withdraw, де-факто P2P transfer (серая
# зона 2 в COMPLIANCE_REWORK_PLAN.md). Marriage остаётся как чисто social
# механика: статус, partner, эмодзи в чате/overlay.


from routes.misc import get_twitch_app_token  # noqa: E402


async def run_migrations():
    """Применяем миграции БД"""
    async with aiosqlite.connect(db.db_path) as conn:
        # Добавляем hediff_type если нет
        try:
            await conn.execute("ALTER TABLE rimworld_pawn_hediffs ADD COLUMN hediff_type TEXT DEFAULT 'injury'")
            await conn.commit()
            print("✅ Migration: hediff_type добавлен")
        except aiosqlite.OperationalError as e:
            if 'duplicate column name' not in str(e).lower():
                print(f"⚠️ Migration warning (hediff_type): {e}")
            # else: already exists — expected

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
            except aiosqlite.OperationalError as e:
                if 'duplicate column name' not in str(e).lower():
                    print(f"⚠️ Migration warning ({col}): {e}")
                # else: already exists — expected
        # Добавляем is_disabled в rimworld_pawn_skills если нет
        try:
            await conn.execute("ALTER TABLE rimworld_pawn_skills ADD COLUMN is_disabled INTEGER DEFAULT 0")
            await conn.commit()
            print("✅ Migration: is_disabled добавлен в rimworld_pawn_skills")
        except aiosqlite.OperationalError as e:
            if 'duplicate column name' not in str(e).lower():
                print(f"⚠️ Migration warning (is_disabled): {e}")
            # else: already exists — expected

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
                       END WHERE skill_name = ?""",  # tenant-ok: one-time startup skill_name migration, must touch all channels
                    (_rus, _eng, _rus))
            except aiosqlite.OperationalError as e:
                print(f"⚠️ Migration warning (skill_name remap {_rus}): {e}")
        await conn.commit()
        print("✅ Migration: skill_name локализация исправлена")

        # ── M1: multi-tenant schema (channel_id во все TENANT-таблицы) ──
        # Идемпотентно через `migrations_applied`. На single-tenant базе backfill'ит
        # существующие строки текущим TWITCH_BROADCASTER_ID.
        # См. docs/MULTITENANT_PLAN.md и backend/migrations/m1_multitenant.py
        try:
            from migrations import m1_multitenant
            await m1_multitenant.apply(conn)
        except Exception as e:
            print(f"❌ M1 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M4: channels registry — реестр зарегистрированных стримеров ──
        try:
            from migrations import m4_channels
            await m4_channels.apply(conn)
        except Exception as e:
            print(f"❌ M4 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M5: module_actions — outbox очередь для Module API ──
        try:
            from migrations import m5_module_actions
            await m5_module_actions.apply(conn)
        except Exception as e:
            print(f"❌ M5 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M6: module_catalogs — generic catalog хранилище для Module API ──
        try:
            from migrations import m6_module_catalogs
            await m6_module_catalogs.apply(conn)
        except Exception as e:
            print(f"❌ M6 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M7: drop unused activity metrics (active_clicks, active_moves) ──
        try:
            from migrations import m7_drop_active_metrics
            await m7_drop_active_metrics.apply(conn)
        except Exception as e:
            print(f"❌ M7 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M8: compliance cleanup (Phase 1 of COMPLIANCE_REWORK_PLAN.md) ──
        # DROP TABLE casino_settings, free_spins_daily, craft_stats, market_listings
        # REFUND pending_duels.amount → creator + DROP COLUMN
        # REFUND marriages.family_balance → user1/user2 50/50 + DROP COLUMN
        try:
            from migrations import m8_compliance_cleanup
            await m8_compliance_cleanup.apply(conn)
        except Exception as e:
            print(f"❌ M8 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M9: cases (Phase 2 of COMPLIANCE_REWORK_PLAN.md) ──
        # cases + case_triggers_fired tables (4 tiers fixed rewards)
        try:
            from migrations import m9_cases
            await m9_cases.apply(conn)
        except Exception as e:
            print(f"❌ M9 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M10: matchmaking base (Phase 5.0 of COMPLIANCE_REWORK_PLAN.md) ──
        # match_queue + match_rooms tables, rebuild duel_stats / duel_seasons
        # с channel_id + game_type в PK, DROP legacy pending_duels
        try:
            from migrations import m10_matchmaking
            await m10_matchmaking.apply(conn)
        except Exception as e:
            print(f"❌ M10 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M11: guilds base (Phase 3 of COMPLIANCE_REWORK_PLAN.md) ──
        # guilds + members + skills + contributions tables
        try:
            from migrations import m11_guilds
            await m11_guilds.apply(conn)
        except Exception as e:
            print(f"❌ M11 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M12: voting events (Phase 4 of COMPLIANCE_REWORK_PLAN.md) ──
        # streamer_voting_templates + voting_events + voting_options +
        # voting_bids + voting_pool_counters
        try:
            from migrations import m12_voting
            await m12_voting.apply(conn)
        except Exception as e:
            print(f"❌ M12 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M13: pets MVP (Phase 7 of COMPLIANCE_REWORK_PLAN.md) ──
        # Первая cross-channel feature. pet_catalog + pets + pet_inventory +
        # pet_equipped + pet_purchases + channel_pet_settings. Catalog seeded.
        try:
            from migrations import m13_pets
            await m13_pets.apply(conn)
        except Exception as e:
            print(f"❌ M13 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M14: bannerlord — второй gaming-модуль платформы ──
        # bannerlord_heroes + bannerlord_skills + bannerlord_attributes +
        # bannerlord_equipment + bannerlord_events_log. TENANT-scoped.
        # См. docs/BANNERLORD_MVP.md §3 + Sprint 1.
        try:
            from migrations import m14_bannerlord
            await m14_bannerlord.apply(conn)
        except Exception as e:
            print(f"❌ M14 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M15: bannerlord classes (Sprint 4.1) ──
        # 13 seeded classes (Tank/Archer/Cavalry/...) + bannerlord_hero_class
        # binding table. BLT-style class system, clean-room re-impl.
        try:
            from migrations import m15_bannerlord_classes
            await m15_bannerlord_classes.apply(conn)
        except Exception as e:
            print(f"❌ M15 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M16: bannerlord class passive powers (Sprint 4.2) ──
        # bannerlord_class_powers — per-class power scaling (lvl1/2/3).
        try:
            from migrations import m16_bannerlord_class_powers
            await m16_bannerlord_class_powers.apply(conn)
        except Exception as e:
            print(f"❌ M16 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M17: EventSub dedupe (Phase A) ──
        # eventsub_seen table — идемпотентность Twitch webhook retry'ев.
        try:
            from migrations import m17_eventsub_dedupe
            await m17_eventsub_dedupe.apply(conn)
        except Exception as e:
            print(f"❌ M17 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M18: armor_bypass→ignore_armor fixup + bannerlord active powers ──
        # Объединяет дубликат armor_bypass_pct → ignore_armor_pct и seed'ит
        # active powers (shield_break_burst / rage / retribution_toggle).
        # Перенумерован с M17 чтобы не конфликтовать с m17_eventsub_dedupe.
        try:
            from migrations import m18_bannerlord_active_powers
            await m18_bannerlord_active_powers.apply(conn)
        except Exception as e:
            print(f"❌ M18 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M19: bannerlord_heroes meta (level / clan_name / kingdom_name) ──
        # Расширяет hero card UI — viewer видит уровень, клан, королевство.
        try:
            from migrations import m19_bannerlord_hero_meta
            await m19_bannerlord_hero_meta.apply(conn)
        except Exception as e:
            print(f"❌ M19 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M20: bannerlord_heroes.gear_tier (6-tier equipment progression) ──
        # !снаряга / extension upgrade button — viewer прокачивает snar 0→6.
        try:
            from migrations import m20_bannerlord_gear_tier
            await m20_bannerlord_gear_tier.apply(conn)
        except Exception as e:
            print(f"❌ M20 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M21: bannerlord_equipment + stats (tier/value/weight/stats_json) ──
        # Mod пушит полные stats per slot. UI показывает badges
        # (T3 ★ / ⚔️ 95dmg / 🛡 50 / 🏇 50spd).
        try:
            from migrations import m21_bannerlord_equipment_stats
            await m21_bannerlord_equipment_stats.apply(conn)
        except Exception as e:
            print(f"❌ M21 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M22: bannerlord_channel_state (save-switch tracking) ──
        # При смене save в-игре mod пушит session_start с новым UniqueGameId.
        # Backend reset'ит heroes если save_id изменился.
        try:
            from migrations import m22_bannerlord_channel_state
            await m22_bannerlord_channel_state.apply(conn)
        except Exception as e:
            print(f"❌ M22 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M23: bannerlord_retinue (BLT-style свита) ──
        # Per-hero retinue list. Mod при player.spawn спавнит retinue
        # рядом с hero. hero.recruit_troops добавляет/прокачивает.
        try:
            from migrations import m23_bannerlord_retinue
            await m23_bannerlord_retinue.apply(conn)
        except Exception as e:
            print(f"❌ M23 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M24: bannerlord_tournament_queue + state ──
        # BLT-style viewer tournaments. Очередь + run-time state.
        try:
            from migrations import m24_bannerlord_tournament
            await m24_bannerlord_tournament.apply(conn)
        except Exception as e:
            print(f"❌ M24 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M25: bannerlord_tournament_bets ──
        # Ставки на участников турнира (крустики).
        try:
            from migrations import m25_bannerlord_tournament_bets
            await m25_bannerlord_tournament_bets.apply(conn)
        except Exception as e:
            print(f"❌ M25 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M26: bannerlord_skills.focus column ──
        # BLT-style focus points per skill (0-5).
        try:
            from migrations import m26_bannerlord_focus
            await m26_bannerlord_focus.apply(conn)
        except Exception as e:
            print(f"❌ M26 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M27: clan_info_json + kingdom_info_json columns ──
        # Structured info для UI модалов (leader, tier, renown, fiefs etc.).
        try:
            from migrations import m27_bannerlord_clan_kingdom_info
            await m27_bannerlord_clan_kingdom_info.apply(conn)
        except Exception as e:
            print(f"❌ M27 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M28: is_elite column в bannerlord_retinue ──
        # BLT-style elite retinue (EliteBasicTroop chain, 3× cost).
        try:
            from migrations import m28_bannerlord_retinue_elite
            await m28_bannerlord_retinue_elite.apply(conn)
        except Exception as e:
            print(f"❌ M28 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M29: pets schema v2 (face+aura slots, svg_path, scarf→body) ──
        # Sprint 5.21: расширили slot set с 4 до 6 чтобы items накладывались
        # на правильные части creature'а (очки → лицо, шарф → грудь).
        try:
            from migrations import m29_pets_slots_v2
            await m29_pets_slots_v2.apply(conn)
        except Exception as e:
            print(f"❌ M29 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M30: pets catalog expansion (+15 items, total → 20) ──
        # Sprint 5.22: после редизайна creature'а добавляем больше косметик
        # под каждый slot (особенно accessory + aura — были пустые).
        try:
            from migrations import m30_pets_catalog_expand
            await m30_pets_catalog_expand.apply(conn)
        except Exception as e:
            print(f"❌ M30 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M31: deprecate 4 misfit items ──
        # Emoji с встроенным человеческим телом (маска/галстук/ковбойская/шарф)
        # плохо смотрелись на blob'е — deprecated.
        try:
            from migrations import m31_pets_deprecate_misfits
            await m31_pets_deprecate_misfits.apply(conn)
        except Exception as e:
            print(f"❌ M31 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M32: hard-delete misfit items ──
        # Тестеры ещё не получили доступ — safe удалить навсегда вместо
        # soft-deprecate. Items: face_mask / body_tie / hat_cowboy / acc_scarf.
        try:
            from migrations import m32_pets_delete_misfits
            await m32_pets_delete_misfits.apply(conn)
        except Exception as e:
            print(f"❌ M32 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M33: TTS messages queue ──
        # Sprint 5.23: платный TTS-донат (5000💎 за сообщение).
        try:
            from migrations import m33_tts_messages
            await m33_tts_messages.apply(conn)
        except Exception as e:
            print(f"❌ M33 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M34: TTS audio_data BLOB ──
        # Sprint 5.23 patch: OBS Browser Source плохо поддерживает Web Speech
        # API — переключение на server-side gTTS + mp3 BLOB в DB.
        try:
            from migrations import m34_tts_audio_blob
            await m34_tts_audio_blob.apply(conn)
        except Exception as e:
            print(f"❌ M34 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M35: Bannerlord clan upgrades (BLT-style) ──
        # Sprint 5.26: catalog + owned tables + seed 10 upgrades.
        try:
            from migrations import m35_clan_upgrades
            await m35_clan_upgrades.apply(conn)
        except Exception as e:
            print(f"❌ M35 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M36: Bannerlord hero family info ──
        # Sprint 5.27c: + is_female, family_info_json в bannerlord_heroes.
        try:
            from migrations import m36_bannerlord_family
            await m36_bannerlord_family.apply(conn)
        except Exception as e:
            print(f"❌ M36 migration FAILED: {type(e).__name__}: {e}")
            raise

        # ── M37: Pets v3 clean slate ──
        # Sprint 5.28: wipe emoji-era pets data, rebuild catalog with
        # 'mythic' rarity + png_path column. Items (catalog rows) добавятся
        # отдельной миграцией M38 когда PixelLab batch готов.
        try:
            from migrations import m37_pets_v3_clean_slate
            await m37_pets_v3_clean_slate.apply(conn)
        except Exception as e:
            print(f"❌ M37 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.29 / BLT-parity #7 — iteration counter для heir succession.
        try:
            from migrations import m38_hero_iteration
            await m38_hero_iteration.apply(conn)
        except Exception as e:
            print(f"❌ M38 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.29 / BLT-parity #5 — achievements система.
        try:
            from migrations import m39_bannerlord_achievements
            await m39_bannerlord_achievements.apply(conn)
        except Exception as e:
            print(f"❌ M39 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.29 / BLT-parity #6 — custom items / smithing trophies.
        try:
            from migrations import m40_custom_items
            await m40_custom_items.apply(conn)
        except Exception as e:
            print(f"❌ M40 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.29 / BLT-parity #6 phase B — auction system.
        try:
            from migrations import m41_auctions
            await m41_auctions.apply(conn)
        except Exception as e:
            print(f"❌ M41 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.31 #45 — Boosty manual-list subscribers
        try:
            from migrations import m42_boosty_subscribers
            await m42_boosty_subscribers.apply(conn)
        except Exception as e:
            print(f"❌ M42 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.32 — is_wounded column для KO state
        try:
            from migrations import m43_hero_wounded
            await m43_hero_wounded.apply(conn)
        except Exception as e:
            print(f"❌ M43 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.32 — active powers для всех классов
        try:
            from migrations import m44_class_actives_for_all
            await m44_class_actives_for_all.apply(conn)
        except Exception as e:
            print(f"❌ M44 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.32 (BLT-parity #46) — daily reward claims
        try:
            from migrations import m45_daily_claims
            await m45_daily_claims.apply(conn)
        except Exception as e:
            print(f"❌ M45 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.32 (BLT-parity H1) — client_action_id idempotency
        try:
            from migrations import m46_client_action_id
            await m46_client_action_id.apply(conn)
        except Exception as e:
            print(f"❌ M46 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.32 (BLT-parity H8) — tournament_wins для persistent anti-snowball
        try:
            from migrations import m47_tournament_wins
            await m47_tournament_wins.apply(conn)
        except Exception as e:
            print(f"❌ M47 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.32 (BLT-parity M2) — heir queue foundation
        try:
            from migrations import m48_heir_queue
            await m48_heir_queue.apply(conn)
        except Exception as e:
            print(f"❌ M48 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.33 (BLT-parity FAM) — viewer↔viewer marriage proposals между детьми
        try:
            from migrations import m49_marriage_proposals
            await m49_marriage_proposals.apply(conn)
        except Exception as e:
            print(f"❌ M49 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.33 (BLT-parity FX) — character effects (poison/disarm/charge)
        try:
            from migrations import m50_character_effects
            await m50_character_effects.apply(conn)
        except Exception as e:
            print(f"❌ M50 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.33 (BLT-parity ITEM) — rolled stats для custom items (trophy bonuses)
        try:
            from migrations import m51_custom_item_stats
            await m51_custom_item_stats.apply(conn)
        except Exception as e:
            print(f"❌ M51 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.33 (BLT-parity VAS) — vassal sub-clan system
        try:
            from migrations import m52_vassals
            await m52_vassals.apply(conn)
        except Exception as e:
            print(f"❌ M52 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.33 (BLT-parity SIEGE) — party orders (siege/defend/raid/etc.)
        try:
            from migrations import m53_party_orders
            await m53_party_orders.apply(conn)
        except Exception as e:
            print(f"❌ M53 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.33 (BLT-parity DIPLO) — kingdom policies + peace + ransom
        try:
            from migrations import m54_diplomacy
            await m54_diplomacy.apply(conn)
        except Exception as e:
            print(f"❌ M54 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.33 (BLT-parity SHOP) — workshops passive income loop
        try:
            from migrations import m55_workshops
            await m55_workshops.apply(conn)
        except Exception as e:
            print(f"❌ M55 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.33 (BLT-parity FIEF) — fief tribute passive income
        try:
            from migrations import m56_fiefs
            await m56_fiefs.apply(conn)
        except Exception as e:
            print(f"❌ M56 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.33 (BLT-parity CARAVAN) — mobile caravans + rescue pool
        try:
            from migrations import m57_caravans
            await m57_caravans.apply(conn)
        except Exception as e:
            print(f"❌ M57 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Sprint 5.33 (BLT-parity HERITAGE) — inheritance audit log
        try:
            from migrations import m58_inheritance
            await m58_inheritance.apply(conn)
        except Exception as e:
            print(f"❌ M58 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Backlog #1 (BLT-RC22 C.5) — kingdom tax rate (display projection)
        try:
            from migrations import m59_kingdom_tax
            await m59_kingdom_tax.apply(conn)
        except Exception as e:
            print(f"❌ M59 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Inventory unification Phase B — custom_items source/claimed
        try:
            from migrations import m60_custom_items_source
            await m60_custom_items_source.apply(conn)
        except Exception as e:
            print(f"❌ M60 migration FAILED: {type(e).__name__}: {e}")
            raise

        # BLT-parity combat powers — lifesteal / iron-skin / cleave
        try:
            from migrations import m61_combat_powers
            await m61_combat_powers.apply(conn)
        except Exception as e:
            print(f"❌ M61 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Balance pass — combat powers для ranged-классов (M61 их пропустил)
        try:
            from migrations import m62_combat_powers_ranged
            await m62_combat_powers_ranged.apply(conn)
        except Exception as e:
            print(f"❌ M62 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Active power «взрывные стрелы» (BLT AddDamagePower AoE) для ranged
        try:
            from migrations import m63_explosive_arrows
            await m63_explosive_arrows.apply(conn)
        except Exception as e:
            print(f"❌ M63 migration FAILED: {type(e).__name__}: {e}")
            raise

        # Лук/арбалет: 1H в ближний бой + второй колчан (catalog витрина)
        try:
            from migrations import m64_ranged_loadout_quivers
            await m64_ranged_loadout_quivers.apply(conn)
        except Exception as e:
            print(f"❌ M64 migration FAILED: {type(e).__name__}: {e}")
            raise

        # BLT-parity power BOOST — масштабирует значения способностей в новый
        # headroom мод-капов (rage 8×, lifesteal 250/hit, reduction 90%, HP 2.5×).
        try:
            from migrations import m65_power_boost
            await m65_power_boost.apply(conn)
        except Exception as e:
            print(f"❌ M65 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m66_party_info
            await m66_party_info.apply(conn)
        except Exception as e:
            print(f"❌ M66 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m67_melee_balance
            await m67_melee_balance.apply(conn)
        except Exception as e:
            print(f"❌ M67 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m68_stagger_buff
            await m68_stagger_buff.apply(conn)
        except Exception as e:
            print(f"❌ M68 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m69_combat_ai
            await m69_combat_ai.apply(conn)
        except Exception as e:
            print(f"❌ M69 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m70_combat_stance
            await m70_combat_stance.apply(conn)
        except Exception as e:
            print(f"❌ M70 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m71_hp_rebalance
            await m71_hp_rebalance.apply(conn)
        except Exception as e:
            print(f"❌ M71 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m72_feature_usage
            await m72_feature_usage.apply(conn)
        except Exception as e:
            print(f"❌ M72 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m73_bug_reports
            await m73_bug_reports.apply(conn)
        except Exception as e:
            print(f"❌ M73 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m74_sub_greet_settings
            await m74_sub_greet_settings.apply(conn)
        except Exception as e:
            print(f"❌ M74 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m75_watch_streaks
            await m75_watch_streaks.apply(conn)
        except Exception as e:
            print(f"❌ M75 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m76_drop_caravan_rescue_pool
            await m76_drop_caravan_rescue_pool.apply(conn)
        except Exception as e:
            print(f"❌ M76 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m77_equipment_quality
            await m77_equipment_quality.apply(conn)
        except Exception as e:
            print(f"❌ M77 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m78_cleave_active
            await m78_cleave_active.apply(conn)
        except Exception as e:
            print(f"❌ M78 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m79_class_balance
            await m79_class_balance.apply(conn)
        except Exception as e:
            print(f"❌ M79 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m80_class_overhaul
            await m80_class_overhaul.apply(conn)
        except Exception as e:
            print(f"❌ M80 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m81_drop_disarm
            await m81_drop_disarm.apply(conn)
        except Exception as e:
            print(f"❌ M81 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m82_lifesteal_baseline
            await m82_lifesteal_baseline.apply(conn)
        except Exception as e:
            print(f"❌ M82 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m83_shedcolony
            await m83_shedcolony.apply(conn)
        except Exception as e:
            print(f"❌ M83 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m84_shedcolony_capacity
            await m84_shedcolony_capacity.apply(conn)
        except Exception as e:
            print(f"❌ M84 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m85_shedcolony_state_json
            await m85_shedcolony_state_json.apply(conn)
        except Exception as e:
            print(f"❌ M85 migration FAILED: {type(e).__name__}: {e}")

        try:
            from migrations import m86_pets_reseed_crustics
            await m86_pets_reseed_crustics.apply(conn)
        except Exception as e:
            print(f"❌ M86 migration FAILED: {type(e).__name__}: {e}")

        try:
            from migrations import m87_pets_skins_only
            await m87_pets_skins_only.apply(conn)
        except Exception as e:
            print(f"❌ M87 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m88_game_vote_proposals
            await m88_game_vote_proposals.apply(conn)
        except Exception as e:
            print(f"❌ M88 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m89_attendance_first_seen
            await m89_attendance_first_seen.apply(conn)
        except Exception as e:
            print(f"❌ M89 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m90_shedcolony_targets
            await m90_shedcolony_targets.apply(conn)
        except Exception as e:
            print(f"❌ M90 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m91_shedcolony_world
            await m91_shedcolony_world.apply(conn)
        except Exception as e:
            print(f"❌ M91 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m92_classes_v2
            await m92_classes_v2.apply(conn)
        except Exception as e:
            print(f"❌ M92 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m93_classes_v2_balance
            await m93_classes_v2_balance.apply(conn)
        except Exception as e:
            print(f"❌ M93 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m94_assassin_return
            await m94_assassin_return.apply(conn)
        except Exception as e:
            print(f"❌ M94 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m95_passives_audit
            await m95_passives_audit.apply(conn)
        except Exception as e:
            print(f"❌ M95 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m96_policy_requests_unstick
            await m96_policy_requests_unstick.apply(conn)
        except Exception as e:
            print(f"❌ M96 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m97_rimworld_tenant_scope
            await m97_rimworld_tenant_scope.apply(conn)
        except Exception as e:
            print(f"❌ M97 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m98_rimworld_dedup_key
            await m98_rimworld_dedup_key.apply(conn)
        except Exception as e:
            print(f"❌ M98 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m99_channel_approval
            await m99_channel_approval.apply(conn)
        except Exception as e:
            print(f"❌ M99 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m100_feature_usage_context
            await m100_feature_usage_context.apply(conn)
        except Exception as e:
            print(f"❌ M100 migration FAILED: {type(e).__name__}: {e}")
            raise

        try:
            from migrations import m101_peace_offer_action_id
            await m101_peace_offer_action_id.apply(conn)
        except Exception as e:
            print(f"❌ M101 migration FAILED: {type(e).__name__}: {e}")
            raise

        print("✅ Migrations complete")


# ===== TWITCH IRC БОТ (отслеживание чата) =====

class TwitchChatBot(twitch_commands.Bot):
    """Multi-channel IRC бот (M4 follow-up в).

    На startup джойнит ВСЕ зарегистрированные в `channels` каналы. При входящем
    чате/USERNOTICE из канала #X — резолвит channel_id через login→id mapping
    из dependencies, ставит в ContextVar, дальше DB-helpers/quest-progress
    автоматически скоупятся правильно.

    Late-join (новый стример OAuth-нулся после старта бота) — TODO future:
    twitchio supports `await self.join_channels([login])`, нужно вызывать из
    OAuth callback'а или периодической reconciliation-таски.
    """

    def __init__(self, channel_logins: list):
        token = os.getenv('TWITCH_OAUTH_TOKEN', '')
        if not token:
            print("TWITCH_OAUTH_TOKEN не задан — IRC бот не запустится")
            return
        if not channel_logins:
            # Защита: бот без каналов не несёт пользы. Лучше явный warning + skip.
            print("⚠️  Список зарегистрированных каналов пуст — IRC бот не джойнит чаты")
            return
        clean = [c.lower().strip().lstrip('#') for c in channel_logins if c]
        super().__init__(token=token, prefix='!', initial_channels=clean)
        self._channel_logins = clean
        # Default = первый канал из реестра. Используется когда выходящий
        # send_message не имеет channel-контекста (legacy callers без ContextVar).
        self._default_channel = clean[0]
        print(f"🎮 TwitchChatBot инициализирован для каналов: {clean}")

    async def event_ready(self):
        print(f"✅ IRC бот подключён как {self.nick} к каналам: {self._channel_logins}")
        # Передаём ссылку на себя в BotCore чтобы send_message работал
        bot.twitch_bot = self
        # Флашим сообщения которые накопились пока IRC подключался
        # (иначе end_event-оповещения из event_watcher_loop, стартовавшего
        # раньше IRC, уходили в "[CHAT LOG]" и не попадали в Twitch).
        try:
            await bot.flush_pending_chat()
        except Exception as e:
            print(f"flush_pending_chat error: {e}")

    async def send_message(self, message: str, channel_login: Optional[str] = None):
        """Отправить сообщение в указанный канал (или default = первый из join'нутых).

        M4 follow-up (в): channel_login параметр. Без него — fallback на
        _default_channel чтобы legacy-вызовы из BotCore без channel-контекста
        не сломались (single-tenant поведение остаётся как было).
        """
        target = (channel_login or self._default_channel or '').lower().lstrip('#')
        if not target:
            print(f"send_message: нет default канала — drop: {message}")
            return
        try:
            ch = self.get_channel(target)
            if ch:
                await ch.send(message)
                print(f"📢 [CHAT #{target}] {message}")
            else:
                print(f"Канал #{target} не найден в IRC-кэше — drop: {message}")
        except Exception as e:
            print(f"send_message error: {e}")

    async def event_message(self, message):
        if message.echo:
            return
        username = message.author.name.lower() if message.author else None
        if not username:
            return
        text = message.content or ''
        try:
            # M4 follow-up (в): резолвим channel_id из twitchio ctx + ставим в ContextVar
            # Делаем это ДО update_viewer_chat — чтобы ключ был tuple-correct.
            from dependencies import (
                get_channel_id_by_login,
                set_request_channel_id,
                resolve_channel_id_or_default,
            )
            chat_login = (getattr(message.channel, 'name', '') or '').lower().lstrip('#')
            channel_id = get_channel_id_by_login(chat_login) or resolve_channel_id_or_default()
            set_request_channel_id(channel_id)
            # !баг / !bug <текст> — приём багрепорта от зрителя (m73). Перехватываем
            # ДО bonus/quest: команда не считается за обычное чат-сообщение.
            _bcmd = text.lstrip().split(maxsplit=1)
            if _bcmd and _bcmd[0].lower() in ('!баг', '!bug'):
                await self._handle_bug_report(
                    channel_id, username, _bcmd[1] if len(_bcmd) > 1 else '')
                return
            # Сбрасываем AFK — зритель написал в чат (per-channel presence trace)
            bot.update_viewer_chat(username, channel_id)
            async with db._connect() as conn:
                await conn.execute("""
                    INSERT INTO viewers (channel_id, username, last_seen, is_afk)
                    VALUES (?, ?, datetime('now'), 0)
                    ON CONFLICT(channel_id, username) DO UPDATE SET
                        last_seen = datetime('now'), is_afk = 0
                """, (channel_id, username))
                await conn.execute("""
                    INSERT INTO chat_stats (channel_id, username, message_length, message_text)
                    VALUES (?, ?, ?, ?)
                """, (channel_id, username, len(text), None))  # never store message content (privacy)
                await conn.commit()
            # M7: Бонус за сообщение через антифрод-helper.
            # Проверяет cooldown (10s) + min length (10ch) + dedup last 10 hashes.
            bonus = bot.compute_chat_bonus(channel_id, username, text)
            if bonus > 0:
                await db.add_points(username, bonus, channel_id=channel_id)
            # Phase 4: voting pool += VOTING_POOL_PER_CHAT_MSG за каждое
            # сообщение (антифрод уже отсеял дубли в bonus check)
            try:
                from config import VOTING_POOL_PER_CHAT_MSG
                await db.increment_voting_pool(channel_id, VOTING_POOL_PER_CHAT_MSG)
            except Exception:
                pass
            # Обновляем чат-квесты
            await bot._update_quest_progress(username, 'chat_messages_10', 1)
            await bot._update_quest_progress(username, 'chat_messages_25', 1)
            await bot._update_quest_progress(username, 'chat_messages_50', 1)
            await bot._update_quest_progress(username, 'chat_messages_100', 1)
        except Exception as e:
            print(f"IRC chat error: {e}")

    async def _handle_bug_report(self, channel_id, username, arg):
        """!баг <текст> — сохранить багрепорт + ответить зрителю в чат (m73).

        Анти-спам: кулдаун per (channel_id, username). Пустой текст → подсказка.
        Стример читает багрепорты в дашборде (карточка «🐞 Баг-репорты»).
        """
        try:
            import bug_reports
            msg = (arg or '').strip()
            if not msg:
                await bot.send_message(
                    f"@{username} напиши описание: !баг <что сломалось>",
                    channel_id=channel_id)
                return
            left = bug_reports.cooldown_left(channel_id, username)
            if left > 0:
                await bot.send_message(
                    f"@{username} подожди {left}с перед следующим багрепортом",
                    channel_id=channel_id)
                return
            await bug_reports.record_bug_report(channel_id, username, msg)
            bug_reports.mark_reported(channel_id, username)
            await bot.send_message(
                f"✅ @{username} баг записан — спасибо! Стример увидит.",
                channel_id=channel_id)
        except Exception as e:
            print(f"!баг handler error: {e}")

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

            # M4 follow-up (в): извлечь канал из IRC line `... USERNOTICE #channel ...`
            # и поставить channel_id в ContextVar для downstream db-helpers.
            chat_login = ""
            try:
                un_idx = data.index('USERNOTICE')
                tail = data[un_idx + len('USERNOTICE'):].lstrip()
                if tail.startswith('#'):
                    chat_login = tail.split(maxsplit=1)[0].lstrip('#').lower()
            except ValueError:
                pass
            from dependencies import (
                get_channel_id_by_login,
                set_request_channel_id,
                resolve_channel_id_or_default,
            )
            channel_id = get_channel_id_by_login(chat_login) or resolve_channel_id_or_default()
            set_request_channel_id(channel_id)

            print(f"🔥 Milestone: @{username} смотрит {streak} стримов подряд! (channel #{chat_login})")

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

            # Проверяем что уже не выдавали эту награду за этот стрик (BEGIN IMMEDIATE — атомарно).
            # channel_id уже корректно вычислен выше из chat_login (~стр.1393) — НЕ
            # перетираем его resolve_default'ом (старый multi-tenant баг: уходило на дефолт).
            async with db._connect() as conn:
                await conn.execute("BEGIN IMMEDIATE")
                cursor = await conn.execute(
                    "SELECT id FROM streak_rewards WHERE channel_id=? AND username=? AND streak_count=?",
                    (channel_id, username, matched_streak)
                )
                already_given = await cursor.fetchone()
                if already_given:
                    await conn.execute("ROLLBACK")
                    print(f"⏭️ Награда за стрик {matched_streak} уже выдана @{username}")
                    return
                await conn.execute(
                    "INSERT INTO streak_rewards (channel_id, username, streak_count, diamonds_given) VALUES (?,?,?,?)",
                    (channel_id, username, matched_streak, reward)
                )
                # Начисление В ТОЙ ЖЕ транзакции, что и dedup-запись (иначе награда
                # могла не доехать после commit'а dedup) + channel_id явно (раньше
                # add_points без него → resolve на ContextVar/default в bot-контексте).
                await db.add_points_tx(conn, username, reward, channel_id)
                await conn.commit()

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

# ===== EVENTSUB: SUBSCRIPTIONS REGISTRATION =====
# Webhook handler вынесен в backend/eventsub.py (Phase A, 2026-05-16).
# Здесь только startup-регистрация типов подписок: channel_points + stream.online/offline.

async def register_eventsub_subscriptions():
    """Регистрирует все Phase A EventSub-подписки для зарегистрированных каналов.

    Типы (PHASE_A_SUBSCRIPTIONS в eventsub.py):
      - channel.channel_points_custom_reward_redemption.add
      - stream.online
      - stream.offline

    Webhook EventSub требует App Access Token (client credentials).

    M4.5: при EVENTSUB_AUTO_REGISTER=true — multi-tenant режим (итерируем
    реестр channels). При false (default) — single-tenant (TWITCH_BROADCASTER_ID).
    Каждый тип регистрируется идемпотентно (см. eventsub.register_subscription).
    """
    if not CHANNEL_POINTS_CONFIG.get('enabled'):
        # Флаг сохраняем как master-switch — отключает все EventSub-регистрации,
        # не только channel_points. Это даёт возможность отрубить весь
        # EventSub-flow одним env-флагом если что-то пойдёт не так.
        print("EventSub: CHANNEL_POINTS_CONFIG.enabled=false — регистрация подписок пропущена")
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

        from config import EVENTSUB_AUTO_REGISTER
        from eventsub import register_all_for_broadcaster

        if EVENTSUB_AUTO_REGISTER:
            channels = await db.list_channels()
            if not channels:
                print("EventSub: реестр channels пуст, никого не регистрируем")
                return
            print(
                f"🔍 EventSub: multi-tenant register для {len(channels)} каналов "
                f"(3 типа × N каналов), client_id={client_id[:8]}…"
            )
            async with aiohttp.ClientSession() as session:
                for ch in channels:
                    bid = str(ch['channel_id'])
                    await register_all_for_broadcaster(
                        session, headers, bid, callback_url, secret
                    )
        else:
            broadcaster_id = CHANNEL_POINTS_CONFIG.get('broadcaster_id', '')
            if not broadcaster_id:
                print("EventSub: TWITCH_BROADCASTER_ID не задан в .env")
                return
            print(
                f"🔍 EventSub: single-tenant register, broadcaster_id={broadcaster_id}, "
                f"client_id={client_id[:8]}…"
            )
            async with aiohttp.ClientSession() as session:
                await register_all_for_broadcaster(
                    session, headers, broadcaster_id, callback_url, secret
                )
    except Exception as e:
        print(f"EventSub register error: {e}")


# EventSub webhook handler перенесён в backend/eventsub.py (Phase A, 2026-05-16).
# Routes /eventsub и /eventsub/channel-points (legacy alias) подключаются через
# eventsub_router в app.include_router выше.


async def _dispatched_action_sweeper():
    """Sprint 5.29 audit fix #38 — re-queue stuck dispatched actions.

    Действия в `module_actions` со status='dispatched' могут залипнуть если
    mod упал между fetch и ACK. Viewer заплатил крустики (или гольд), но
    действие не выполнилось и не refund'нулось. Sweeper раз в 5 минут:
      - SELECT * WHERE status='dispatched' AND dispatched_at < now - 10min
      - UPDATE status='queued' WHERE id IN (...)
      - log INFO with count + ids

    После re-queue action попадёт в следующий long-poll mod'а. Если mod
    обработает ОК → ACK success. Если опять refuse → action.failed → refund.
    Idempotent: re-queue не дублирует, просто меняет status.
    """
    sweep_interval_sec = 300       # 5 min
    stale_threshold_sec = 600      # 10 min
    print("🔁 Dispatched-action sweeper started "
          f"(interval={sweep_interval_sec}s, stale_after={stale_threshold_sec}s)")
    while True:
        try:
            await asyncio.sleep(sweep_interval_sec)
            async with db._connect() as conn:
                # Use datetime arithmetic — SQLite datetime('now') is UTC string.
                cur = await conn.execute(
                    "SELECT id, action_id, channel_id, type FROM module_actions "
                    "WHERE status='dispatched' "
                    "  AND dispatched_at IS NOT NULL "
                    "  AND dispatched_at < datetime('now', ?)",
                    (f"-{stale_threshold_sec} seconds",))
                rows = await cur.fetchall()
                if not rows:
                    continue
                ids = [r[0] for r in rows]
                placeholders = ",".join("?" for _ in ids)
                await conn.execute(
                    f"UPDATE module_actions SET status='queued' "
                    f"WHERE id IN ({placeholders})",
                    ids)
                await conn.commit()
                for r in rows:
                    print(f"🔁 [sweeper] re-queued stale dispatched action "
                          f"id={r[0]} action_id={r[1]} ch={r[2]} type={r[3]}")
        except Exception as e:
            print(f"❌ Dispatched-action sweeper error: {type(e).__name__}: {e}")


async def _queued_action_ttl_sweeper():
    """Аудит 2026-07-04: заявка, купленная при ОФЛАЙН игровом сервере, висела в status='queued'
    ВЕЧНО — зритель заплатил, действие не исполнится и не рефандится (_dispatched_action_sweeper
    ловит только 'dispatched'). TTL: queued дольше 30 мин = мод очевидно офлайн → авто-рефанд
    штатным action.failed-путём адаптера (идемпотентен по 'REFUNDED:', помечает failed).

    2026-07-28 — BANNERLORD ПОДКЛЮЧЁН (решение владельца, T-01 + S-11).
    Повод: 27.07 зритель купил призыв за 100 крустиков за полторы минуты до конца
    стрима; мод команду не забрал, и она осталась 'queued' навсегда — ни эффекта,
    ни возврата. Раньше сюда попадал только shedcolony.

    ПОЧЕМУ ЭТО БЕЗОПАСНО ТОЛЬКО СЕЙЧАС. Возврат обязан делать строку
    ТЕРМИНАЛЬНОЙ, иначе получим и деньги назад, и эффект: курсор опроса мода
    (`ActionPoller._cursor`) сбрасывается в 0 при перезапуске игры, и старую
    'queued'-строку он увидит снова. До 2026-07-28 `_on_action_failed` статус не
    менял — подключать было нельзя. Теперь меняет (оба пути: и с ценой, и
    бесплатный), поэтому просроченное действие выпадает из выдачи
    `status='queued'` и повторно не исполнится.
    """
    sweep_interval_sec = 600       # 10 min
    ttl_sec = 1800                 # 30 min queued = the mod is clearly offline
    from modules._loader import get_module
    from modules._base import ModuleEnvelope
    print(f"⏳ Queued-action TTL sweeper started (interval={sweep_interval_sec}s, ttl={ttl_sec}s)")
    while True:
        try:
            await asyncio.sleep(sweep_interval_sec)
            async with db._connect() as conn:
                cur = await conn.execute(
                    "SELECT action_id, channel_id, type, module_id FROM module_actions "
                    "WHERE module_id IN ('shedcolony', 'bannerlord') AND status='queued' "
                    "  AND created_at < datetime('now', ?)",
                    (f"-{ttl_sec} seconds",))
                rows = await cur.fetchall()
            if not rows:
                continue
            for action_id, channel_id, action_type, module_id in rows:
                adapter = get_module(module_id)
                if not adapter:
                    continue
                env = ModuleEnvelope(id=f"ttl_{action_id}", kind="event", type="action.failed",
                                     ts=0, data={"action_id": action_id,
                                                 "reason": "queued_ttl_expired"})
                await adapter.handle_event(channel_id, env)
                print(f"⏳ [ttl-sweeper] auto-refunded stale queued action "
                      f"{action_id} type={action_type} ch={channel_id} module={module_id}")
        except Exception as e:
            print(f"❌ Queued-TTL sweeper error: {type(e).__name__}: {e}")


async def _wal_checkpoint_loop():
    """Блок 1 архитектурной прокачки: periodic WAL maintenance.

    SQLite auto-checkpoint срабатывает при достижении 1000 страниц в WAL,
    но при высокой write-нагрузке без явных pause'ов WAL может расти.
    PASSIVE checkpoint раз в час даёт мониторингу простую гарантию что
    WAL рестарится. RESTART раз в сутки гарантирует возврат к нулевому
    WAL и полную компактизацию.
    """
    hourly_count = 0
    while True:
        try:
            await asyncio.sleep(3600)  # каждый час
            hourly_count += 1
            mode = "RESTART" if (hourly_count % 24) == 0 else "PASSIVE"
            stats = await db.wal_checkpoint(mode)
            if stats:
                print(f"🔄 WAL checkpoint ({mode}): "
                      f"log={stats['log_pages']}p ckpt={stats['checkpointed_pages']}p "
                      f"busy={stats['busy']}")
        except Exception as e:
            print(f"WAL checkpoint loop error: {type(e).__name__}: {e}")


async def start_twitch_bot():
    global _twitch_chat_bot
    # M4 follow-up (в): тянем список каналов из реестра channels (M4.0).
    # Fallback на TWITCH_CHANNEL_NAME — на случай свежего setup до миграции
    # (хотя миграция M4.0 backfill'ит этот канал; defensive belt-and-suspenders).
    try:
        rows = await db.list_channels()
        channel_logins = [r['login'] for r in rows if r.get('login')]
    except Exception as e:
        print(f"⚠️  IRC bot: не удалось прочитать channels из БД: {e}")
        channel_logins = []
    if not channel_logins:
        env_channel = os.getenv('TWITCH_CHANNEL_NAME', '').lower().strip()
        if env_channel:
            channel_logins = [env_channel]
            print(f"⚠️  IRC bot: реестр пуст, fallback на TWITCH_CHANNEL_NAME={env_channel}")
    # Retry loop — пробуем подключиться с паузами при ошибке
    while True:
        try:
            _twitch_chat_bot = TwitchChatBot(channel_logins)
            if not hasattr(_twitch_chat_bot, '_channel_logins'):
                print("IRC бот: токен не задан или нет каналов для джойна")
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
            cursor = await conn.execute("SELECT username FROM viewers WHERE username = ?", (u,))  # tenant-ok: startup pentest-account cleanup, cross-channel intentional
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
        # M4.1: загрузить registered channels в in-memory cache.
        # Должно быть ПОСЛЕ run_migrations() — m4_channels.apply backfill'ит
        # существующего стримера; без этого первая партия запросов получит 403.
        from dependencies import init_registered_channels_cache
        await init_registered_channels_cache(db)
        # Этап 3 step 1: discover game modules (modules/<id>/manifest.yaml)
        from modules._loader import discover_modules
        discover_modules()
        await cleanup_test_accounts()
    except Exception as e:
        print(f"❌ Критическая ошибка при инициализации БД: {e}")
        raise  # Падаем явно — не скрываем проблему
    # STAGING (ROADMAP 1.3): DISABLE_LIVE_INTEGRATIONS=1 запускает бек БЕЗ
    # исходящих-в-Twitch интеграций (IRC-чат-бот, auto-message, EventSub-
    # регистрация, PubSub-drain). Иначе staging-копия зашла бы в ЖИВОЙ канал
    # и слала дубли в чат/расширение зрителям. БД-циклы (points/drops/voting)
    # работают как обычно — их и нужно тестить. Прод не задаёт переменную → 8000 + полный режим.
    _staging = os.getenv("DISABLE_LIVE_INTEGRATIONS", "").lower() in ("1", "true", "yes")
    if _staging:
        print("🧪 STAGING MODE: live Twitch integrations DISABLED (no chat-bot / EventSub / PubSub)")
    # Служебные фоновые задачи
    asyncio.create_task(_rate_cleanup_loop())
    # M5: per-channel rate-limit bucket cleanup (раз в 5 мин)
    from dependencies import channel_rate_cleanup_loop as _channel_rate_cleanup
    asyncio.create_task(_channel_rate_cleanup())
    # Фоновые задачи бота
    asyncio.create_task(bot.reward_points_loop())
    asyncio.create_task(bot.drop_loop())
    asyncio.create_task(bot.matchmaking_loop())  # Phase 5.0 (2026-05-11)
    asyncio.create_task(bot.voting_loop())       # Phase 4 (2026-05-11)
    # market_expiry_loop удалён 2026-05-10 (Phase 1.C compliance rework)
    # Автозавершение рулекционов по таймеру (иначе ивент висит
    # до следующего опроса /api/event/status — и чат-оповещение
    # о победителе не уходит).
    asyncio.create_task(bot.event_manager.event_watcher_loop())
    # IRC бот и семейный доход
    if not _staging:
        asyncio.create_task(start_twitch_bot())
        asyncio.create_task(bot.auto_message_loop())
        # Safety-net для сообщений, поставленных в очередь до коннекта IRC:
        # event_ready() флашит один раз, но если что-то поставилось позже (гонка
        # или transient disconnect), этот цикл каждые 15с добивает хвост.
        asyncio.create_task(bot.pending_chat_flush_loop())
    # run_family_income() удалён 2026-05-10 (Phase 1.G compliance rework)
    # Phase A (2026-05-16): регистрируем три типа подписок (channel_points +
    # stream.online + stream.offline) для всех каналов в реестре.
    if not _staging:
        asyncio.create_task(register_eventsub_subscriptions())
    # TTL cleanup для eventsub_seen — раз в час чистит expired (24h retention).
    from eventsub import cleanup_seen_loop as _eventsub_cleanup
    asyncio.create_task(_eventsub_cleanup())
    # Phase C (2026-05-17): PubSub drain loop — pop'ит per-topic queue с
    # throttle 1msg/sec на (channel, topic) и шлёт в Helix /extensions/pubsub.
    from pubsub import drain_loop as _pubsub_drain
    if not _staging:
        asyncio.create_task(_pubsub_drain())
    # M4 follow-up (б): держим OAuth-токены стримеров свежими. На staging НЕ
    # запускаем — рефреш ротирует живой токен стримера и разлогинил бы прод.
    from routes.streamer import oauth_refresh_loop as _oauth_refresh_loop
    if not _staging:
        asyncio.create_task(_oauth_refresh_loop())
    # Sprint 5.29 audit fix #38: dispatched-action sweeper. Если mod упал
    # между fetch и ACK, action залипает в status='dispatched' forever.
    # Sweeper раз в 5 мин re-queue'ит rows старше 10 мин. Viewer заплатил
    # — действие либо повторится либо refund'нётся через action.failed.
    asyncio.create_task(_dispatched_action_sweeper())
    asyncio.create_task(_queued_action_ttl_sweeper())
    # Sprint 5.29 BLT-parity #6 phase B: auctions resolver loop (every 30s).
    from routes.bannerlord_auctions import auctions_resolve_loop as _auctions_resolve
    asyncio.create_task(_auctions_resolve())
    # Sprint 5.33 IMPROV-1 — stale-channels in-memory cleanup (friend feedback).
    # Раз в 60с проверяет _last_seen и dropит entries из _battle_stats /
    # _active_buffs / _cooldowns / _power_events для каналов offline >10min.
    from modules.bannerlord._adapter import stale_channels_cleanup_loop as _bnr_cleanup
    asyncio.create_task(_bnr_cleanup())
    # Sprint 5.33 PHASE1-1 — DB backup loop (in-process, не зависит от cron).
    # Atomic sqlite .backup каждые BACKUP_INTERVAL_HOURS (default 6h),
    # retain BACKUP_RETAIN_COUNT (default 14). Skips если free disk < 200MB.
    from backup_loop import db_backup_loop as _db_backup
    asyncio.create_task(_db_backup())
    # Sprint 5.33 (BLT-parity FAM): marriage proposals expire loop (every 60s).
    # Mark pending proposals as 'expired' если created+24h < now. Viewer'у никто
    # не отвечает 24h → proposal сам закрывается.
    async def _proposals_expire_loop():
        import asyncio as _asyncio
        from routes.bannerlord_family import expire_old_proposals
        while True:
            try:
                affected = await expire_old_proposals()
                if affected > 0:
                    print(f"[FAM-EXPIRE] marked {affected} proposals as expired")
            except Exception as e:
                print(f"[FAM-EXPIRE] loop crashed: {type(e).__name__}: {e}")
            await _asyncio.sleep(60)
    asyncio.create_task(_proposals_expire_loop())

    # 2026-07-28. Заявка на мир, зависшая в 'pending', держит замок: уникальный
    # индекс частичный (по 'pending'), и тот же король больше не может
    # предложить мир той же фракции. Отказ действия закрывает такую заявку
    # сразу (см. _adapter._drop_placeholder_rows), но у строк, созданных ДО
    # миграции M101, ключа действия нет — их закрываем по возрасту.
    async def _peace_offers_expire_loop():
        import asyncio as _asyncio
        from routes.bannerlord_diplomacy import expire_old_peace_offers
        while True:
            try:
                affected = await expire_old_peace_offers()
                if affected > 0:
                    print(f"[PEACE-EXPIRE] marked {affected} peace offers as expired")
            except Exception as e:
                print(f"[PEACE-EXPIRE] loop crashed: {type(e).__name__}: {e}")
            await _asyncio.sleep(3600)
    asyncio.create_task(_peace_offers_expire_loop())
    # Блок 1 архитектурной прокачки: periodic WAL checkpoint, защита от
    # бесконечного роста WAL-файла. PASSIVE раз в час; раз в сутки —
    # RESTART для более глубокой компактизации.
    asyncio.create_task(_wal_checkpoint_loop())
    # Сезоны дуэлей — проверка при старте по каждому каналу.
    # _load_pending_duels удалён 2026-05-17 (T2) — pending_duels table dropped
    # миграцией M10, persistence теперь in-memory only (5min TTL короче рестартов).
    from routes.duel import check_season_end as _duel_season_check

    async def _check_all_channel_seasons():
        """M4 follow-up (а): итерация check_season_end по реестру каналов.
        Раньше один cross-tenant SELECT — после M1 стало неверно (per-channel)."""
        try:
            channel_rows = await db.list_channels()
        except Exception as e:
            print(f"⚠️ Не удалось прочитать channels для season-check: {e}")
            return
        for r in channel_rows:
            cid = int(r['channel_id'])
            try:
                await _duel_season_check(channel_id=cid)
            except Exception as e:
                print(f"⚠️ check_season_end({cid}) failed: {e}")

    asyncio.create_task(_check_all_channel_seasons())
    print("✅ Сервер запущен")


# Sprint 5.31 #45d (audit HIGH-7,8) — graceful shutdown shared HTTP session.
@app.on_event("shutdown")
async def on_shutdown():
    """Close shared aiohttp.ClientSession (см. http_session.py)."""
    try:
        from http_session import close_session
        await close_session()
    except Exception as e:
        print(f"⚠️ http_session close failed: {e}")

if __name__ == "__main__":
    import asyncio
    import os

    async def _bootstrap():
        # CRITICAL: init_tables ДО run_migrations. На пустой БД миграции M1+
        # ссылаются на таблицы которые создаёт init_tables (activity_stats,
        # viewers, items, etc). Используем temp-пул только в этом event loop
        # (uvicorn потом создаст свой через on_startup).
        await db.init_pool()
        await db.init_tables()
        await run_migrations()
        # Закрываем пул чтобы uvicorn создал свежие connection'ы в своём loop'е
        await db._pool.close()
        db._pool = None
        from db_pool import DBPool
        db._pool = DBPool(db_path=db.db_path, min_size=2, max_size=10, timeout=10.0)

    asyncio.run(_bootstrap())
    import uvicorn

    # Sprint 5.33 PHASE1-2 (2026-05-28) — production server tuning.
    #
    # Why workers=1: backend has IN-PROCESS state (cooldowns, buffs, battle_stats,
    # power_events ring buffer + 5+ background loops: backup, cleanup, sweeper,
    # auctions, proposals expire). Naive workers=N would:
    #   1. Cross-worker state inconsistency (viewer hits worker A, then B → empty cache)
    #   2. Background loops duplicated N× (4× backup writes → race + waste)
    #   3. SQLite WAL: N writer processes still serialize через BEGIN IMMEDIATE
    # Path to true multi-worker = move state к Redis + decouple background loops
    # to dedicated scheduler process. Out of scope for now (1-50 streamer scale).
    #
    # Scaling knobs available SAFELY на single worker:
    #   limit_concurrency: ceiling на concurrent requests (long-polls eat connections)
    #   timeout_keep_alive: HTTP keepalive (default 5s — too short for our long-poll)
    #   backlog: TCP accept queue depth (default 2048 — fine)
    workers = int(os.getenv("UVICORN_WORKERS", "1"))
    limit_concurrency = int(os.getenv("UVICORN_LIMIT_CONCURRENCY", "500"))
    keep_alive = int(os.getenv("UVICORN_KEEP_ALIVE", "30"))   # >25s long-poll timeout
    if workers > 1:
        print(
            f"⚠ WARNING: UVICORN_WORKERS={workers} > 1 — backend has in-process state. "
            "Cooldowns/buffs/battle stats не sync across workers. Background "
            "loops will duplicate. Read main.py PHASE1-2 note before scaling."
        )
    print(f"🚀 uvicorn workers={workers} limit_concurrency={limit_concurrency} keep_alive={keep_alive}s")
    uvicorn.run(
        app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")),   # staging → PORT=8001
        workers=workers if workers > 1 else None,   # None = single async worker
        limit_concurrency=limit_concurrency,
        timeout_keep_alive=keep_alive,
    )

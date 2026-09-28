# -*- coding: utf-8 -*-
"""HTTP contract of the two panels against two channels and a temporary DB."""
import asyncio
import base64
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
for key, value in (
    ("TWITCH_OAUTH_TOKEN", "oauth:test"),
    ("TWITCH_CLIENT_ID", "test"),
    ("TWITCH_CLIENT_SECRET", "test"),
    ("TWITCH_BOT_ID", "test"),
    ("TWITCH_EXTENSION_SECRET", "test-extension-secret-32-bytes-long"),
    ("MODULE_TOKEN_SECRET", "test-module-secret-32-bytes-long"),
    ("ADMIN_PASSWORD", "test-panel-password"),
    ("TWITCH_BROADCASTER_ID", "1"),
):
    os.environ.setdefault(key, value)

import aiosqlite
import httpx
from fastapi import FastAPI
from routes import admin, bannerlord_admin, promo, streamer

fd, path = tempfile.mkstemp(suffix=".db", prefix="panels_contract_")
os.close(fd)


class FakeDB:
    db_path = path

    def _connect(self):
        return aiosqlite.connect(self.db_path)

    async def get_stats(self, channel_id=None):
        return {"channel_id": channel_id}

    async def list_channels(self):
        return [
            {"channel_id": 1, "login": "one", "approved": True},
            {"channel_id": 2, "login": "two", "approved": True},
        ]


db = FakeDB()
admin.get_db = lambda: db
promo.get_db = lambda: db
streamer.get_db = lambda: db

with sqlite3.connect(path) as conn:
    conn.executescript("""
        CREATE TABLE viewers (id INTEGER PRIMARY KEY, channel_id INTEGER, username TEXT,
            points INTEGER, is_afk INTEGER, last_seen TEXT, join_time TEXT);
        CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, display_name TEXT,
            emoji TEXT, rarity TEXT, value INTEGER);
        CREATE TABLE inventory (channel_id INTEGER, username TEXT, item_id INTEGER, quantity INTEGER);
        CREATE TABLE rimworld_pawns (channel_id INTEGER, username TEXT, pawn_name TEXT,
            is_alive INTEGER, health REAL, world_name TEXT);
        CREATE TABLE module_last_seen (channel_id INTEGER, module_id TEXT, last_seen_ts REAL);
        CREATE TABLE rimworld_event_catalog (channel_id INTEGER, id TEXT, name TEXT,
            cost INTEGER, category TEXT);
        CREATE TABLE promocodes (id INTEGER PRIMARY KEY, channel_id INTEGER,
            code TEXT, points INTEGER, item_def TEXT, item_name TEXT,
            max_uses INTEGER, uses INTEGER DEFAULT 0, created_at TEXT,
            UNIQUE(channel_id, code));
        CREATE TABLE promo_uses (channel_id INTEGER, code TEXT, username TEXT);
        CREATE TABLE activity_stats (channel_id INTEGER, username TEXT,
            watch_time INTEGER, created_at TEXT);
        CREATE TABLE chat_stats (channel_id INTEGER, username TEXT,
            created_at TEXT);
        CREATE TABLE module_actions (channel_id INTEGER, type TEXT, data TEXT,
            status TEXT, created_at TEXT);
        INSERT INTO viewers VALUES (1,1,'same',100,0,'2026-09-23','2026-09-01');
        INSERT INTO viewers VALUES (2,1,'alice',150,0,'2026-09-23','2026-09-01');
        INSERT INTO viewers VALUES (3,2,'same',900,0,'2026-09-23','2026-09-01');
        INSERT INTO viewers VALUES (4,2,'bob',300,0,'2026-09-23','2026-09-01');
        INSERT INTO items VALUES (1,'sword','Sword','X','common',10);
        INSERT INTO inventory VALUES (1,'same',1,1);
        INSERT INTO inventory VALUES (2,'same',1,9);
        INSERT INTO rimworld_pawns VALUES (1,'same','Pawn One',1,0.4,'World One');
        INSERT INTO rimworld_pawns VALUES (2,'same','Pawn Two',1,0.8,'World Two');
        INSERT INTO rimworld_event_catalog VALUES (2,'rain','Rain',10,'weather');
        INSERT INTO promocodes (channel_id,code,points,max_uses,uses)
            VALUES (2,'OLD_EMPTY',0,1,0);
        INSERT INTO activity_stats VALUES (1,'same',60,datetime('now'));
        INSERT INTO activity_stats VALUES (2,'same',60,datetime('now'));
        INSERT INTO activity_stats VALUES (2,'same',60,datetime('now','-8 days'));
        INSERT INTO activity_stats VALUES (2,'bob',60,datetime('now'));
        INSERT INTO activity_stats VALUES (2,'old',60,datetime('now','-8 days'));
        INSERT INTO chat_stats VALUES (1,'same',datetime('now'));
        INSERT INTO chat_stats VALUES (2,'bob',datetime('now'));
        INSERT INTO module_actions VALUES (1,'player.spawn','{"initiated_by":"same"}','acked',datetime('now'));
        INSERT INTO module_actions VALUES (2,'player.spawn','{"initiated_by":"alice"}','acked',datetime('now'));
        INSERT INTO module_actions VALUES (2,'power.activate','{"initiated_by":"alice"}','acked',datetime('now'));
        INSERT INTO module_actions VALUES (2,'hero.add_skill','{"initiated_by":"bob"}','acked',datetime('now'));
        INSERT INTO module_actions VALUES (2,'hero.add_skill','{"initiated_by":"old"}','acked',datetime('now','-8 days'));
        INSERT INTO module_actions VALUES (2,'hero.add_skill','{"initiated_by":"failed"}','failed',datetime('now'));
    """)
    conn.execute("INSERT INTO module_last_seen VALUES (2,'rimworld',?)", (time.time(),))
conn.close()

app = FastAPI()
app.include_router(admin.router)
app.include_router(promo.router)
app.include_router(streamer.router)
app.include_router(bannerlord_admin.router)
auth = "Basic " + base64.b64encode(b"admin:test-panel-password").decode()
checks = []


def check(ok, label):
    checks.append((bool(ok), label))
    print(("OK " if ok else "FAIL ") + label)


async def run():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        page = await client.get("/admin")
        check(page.status_code == 200 and "login-overlay" in page.text,
              "admin HTML opens directly to its own login")

        login_missing = await client.get("/api/admin/login")
        check(login_missing.status_code == 401 and
              "www-authenticate" not in login_missing.headers,
              "admin login does not open the browser-native Basic dialog")

        headers = {"Authorization": auth}
        login_valid = await client.get("/api/admin/login", headers=headers)
        check(login_valid.status_code == 200 and login_valid.json().get("success") is True,
              "admin login checks credentials")
        channels = await client.get("/api/admin/channels", headers=headers)
        check(channels.json().get("default_channel_id") == 1,
              "channel picker knows which channel was selected before")
        stats = await client.get("/api/admin/stats?channel_id=2", headers=headers)
        check(stats.status_code == 200 and stats.json().get("channel_id") == 2,
              "admin stats accept selected channel")

        monitoring = await client.get("/api/admin/audience?channel_id=2", headers=headers)
        metrics = monitoring.json() if monitoring.status_code == 200 else {}
        check(metrics.get("watched_7d") == 2 and metrics.get("watched_prev_7d") == 2
              and metrics.get("returned_7d") == 1 and metrics.get("return_rate") == 50
              and metrics.get("chatters_7d") == 1
              and metrics.get("game_participants_7d") == 2
              and metrics.get("game_actions_7d") == 3
              and len(metrics.get("daily", [])) == 7,
              "audience monitoring counts unique viewers, chatters and weekly returns")
        blocked_monitoring = await client.get("/api/admin/audience?channel_id=2")
        check(blocked_monitoring.status_code == 401,
              "audience monitoring requires admin credentials")

        users = await client.get("/api/admin/users?channel_id=2&search=bob", headers=headers)
        d = users.json()
        check(d.get("total") == 1 and len(d.get("users", [])) == 1 and
              d["users"][0]["username"] == "bob", "user search count stays within channel")

        detail = await client.get("/api/admin/user/same?channel_id=2", headers=headers)
        d = detail.json()
        check(d.get("user", {}).get("points") == 900 and
              d.get("inventory", [{}])[0].get("quantity") == 9 and
              d.get("pawn", {}).get("pawn_name") == "Pawn Two",
              "user detail and related data stay within channel")

        status = await client.get("/api/admin/rimworld/status?channel_id=2", headers=headers)
        check(status.status_code == 200 and status.json().get("online") is True,
              "admin RimWorld status uses admin auth")
        pawns = await client.get("/api/admin/rimworld/pawns?channel_id=2", headers=headers)
        d = pawns.json()
        check(pawns.status_code == 200 and len(d.get("pawns", [])) == 1 and
              d["pawns"][0]["health"] == 0.8 and
              d["pawns"][0]["world_name"] == "World Two",
              "admin RimWorld pawns have the panel's shape")
        events = await client.get("/api/admin/rimworld/events?channel_id=2", headers=headers)
        check(events.status_code == 200 and len(events.json().get("events", [])) == 1,
              "admin RimWorld events use admin auth")

        async def preview(channel_id):
            return {"success": True, "channel_id": channel_id}
        bannerlord_admin._reset_preview_data = preview
        bnr = await client.get("/api/admin/bannerlord/reset/preview?channel_id=2",
                               headers=headers)
        check(bnr.json().get("channel_id") == 2,
              "Bannerlord preview follows selected channel")

        bad = await client.post("/api/admin/promocodes/create", headers=headers,
                                json={"channel_id": 2, "code": "EMPTY", "points": 0, "max_uses": 1})
        check(bad.status_code == 200 and bad.json().get("success") is False,
              "admin cannot create an empty reward")
        bad_limit = await client.post("/api/admin/promocodes/create", headers=headers,
                                      json={"channel_id": 2, "code": "NEG", "points": 1, "max_uses": -1})
        check(bad_limit.status_code == 200 and bad_limit.json().get("success") is False,
              "admin cannot create a negative use limit")
        good = await client.post("/api/admin/promocodes/create", headers=headers,
                                 json={"channel_id": 2, "code": "UNLIMITED", "points": 1, "max_uses": 0})
        check(good.status_code == 200 and good.json().get("success") is True,
              "zero use limit remains unlimited")
        item_only = await client.post("/api/admin/promocodes/create", headers=headers,
                                      json={"channel_id": 2, "code": "ITEM", "points": 0,
                                            "item_def": "sword", "max_uses": 1})
        check(item_only.json().get("success") is True,
              "admin may create a real item-only reward")
        missing_item = await client.post("/api/admin/promocodes/create", headers=headers,
                                         json={"channel_id": 2, "code": "MISSING", "points": 0,
                                               "item_def": "unknown", "max_uses": 1})
        check(missing_item.json().get("success") is False,
              "admin cannot create an item reward absent from catalog")

        token = streamer._sign_session(2, int(time.time()) + 60)
        bad_streamer = await client.post("/api/streamer/promocodes/create",
                                         cookies={"streamer_session": token},
                                         json={"code": "NOPE", "points": 0, "max_uses": 1})
        check(bad_streamer.status_code == 200 and
              bad_streamer.json().get("success") is False,
              "streamer cannot create an empty reward")

        class FakeBot:
            async def touch_viewer(self, username, channel_id):
                pass

        async def no_stream_gate():
            return None

        promo.get_bot = lambda: FakeBot()
        promo.require_stream_live = no_stream_gate
        promo.require_jwt_user = lambda request: ("viewer", 2)
        old_code = await client.post("/api/promo/use", json={"code": "OLD_EMPTY"})
        conn = sqlite3.connect(path)
        try:
            uses = conn.execute("SELECT uses FROM promocodes WHERE code='OLD_EMPTY'").fetchone()[0]
            records = conn.execute("SELECT COUNT(*) FROM promo_uses WHERE code='OLD_EMPTY'").fetchone()[0]
        finally:
            conn.close()
        check(old_code.json().get("success") is False and uses == 0 and records == 0,
              "legacy empty code cannot consume a use without a reward")

    return 0 if all(ok for ok, _ in checks) else 1


try:
    raise SystemExit(asyncio.run(run()))
finally:
    os.unlink(path)

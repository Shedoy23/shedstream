# -*- coding: utf-8 -*-
"""Дроп на OBS-оверлее принадлежит своему каналу (24.09.2026).

До: одна глобальная `_overlay_drop` без канала (`dependencies.py`), пишет
`main._on_drop_handler` без `channel_id`, отдаёт `/api/overlay/latest` без
канала. При втором стримере его оверлей покажет дроп зрителя ЧУЖОГО канала —
правило «изолируй ВЫХОД наружу» (CLAUDE.md). Тест держит изоляцию.
Запуск: python tests/test_overlay_drop_per_channel.py  (exit 0 = ок)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _k, _v in {
    "TWITCH_OAUTH_TOKEN": "oauth:test", "TWITCH_CLIENT_ID": "test_client",
    "TWITCH_CLIENT_SECRET": "test_secret", "TWITCH_BOT_ID": "test_bot",
    "TWITCH_CHANNEL_NAME": "test_channel",
    "TWITCH_EXTENSION_SECRET": "test-ext-secret-32bytes-1234567890ab",
    "MODULE_TOKEN_SECRET": "test-module-secret-32bytes-1234567890",
    "ADMIN_PASSWORD": "test_admin_password_for_tests_only",
    "TWITCH_BROADCASTER_ID": "98319857",
}.items():
    os.environ.setdefault(_k, _v)

failed = 0


def check(ok, text):
    global failed
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        failed += 1


async def main():
    import dependencies as d
    from routes import misc
    A, B = 1001, 2002
    d.set_overlay_drop({"username": "зритель_A", "rarity": "rare"}, channel_id=A)
    a = await misc.overlay_latest(channel_id=A)
    b = await misc.overlay_latest(channel_id=B)
    check((a.get("drop") or {}).get("username") == "зритель_A", "оверлей канала A видит свой дроп")
    check(b.get("drop") is None, "оверлей канала B НЕ видит дроп канала A: " + repr(b.get("drop")))
    d.set_overlay_drop({"username": "зритель_B", "rarity": "common"}, channel_id=B)
    a = await misc.overlay_latest(channel_id=A)
    check((a.get("drop") or {}).get("username") == "зритель_A", "дроп канала B не затирает дроп канала A")


asyncio.run(main())
sys.exit(1 if failed else 0)

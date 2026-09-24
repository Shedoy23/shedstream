# -*- coding: utf-8 -*-
"""Лимит приветствий: у чиров свой счётчик, не общий с фолловами (24.09.2026).

До: `_follow_greet_allowed` звали и follow, и cheer — волна фоллов-ботов
(8 за минуту) глушила «спасибо» за биты. Тест: исчерпать лимит фолловов, чир
того же канала всё равно благодарится; лимит фолловов по-прежнему держится.
Запуск: python tests/test_greet_rate_limits.py  (exit 0 = ок)
"""
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


import asyncio
import eventsub as es

sent = []


async def fake_send(channel_id, text):
    sent.append((channel_id, text))


async def always_on(channel_id, kind):
    return True

es._send_greet = fake_send
es._greet_enabled = always_on

CH = 777
for _ in range(es._FOLLOW_GREET_MAX_PER_WINDOW):
    es._follow_greet_allowed(CH)
check(not es._follow_greet_allowed(CH), "лимит фолловов держится: 9-й за минуту не приветствуется")
# Через НАСТОЯЩИЙ обработчик события чира, а не через счётчик напрямую.
asyncio.run(es._on_channel_cheer({"bits": 100, "is_anonymous": False, "user_login": "donor",
                                  "user_name": "donor"}, CH))
check(any(c == CH and "100" in t for c, t in sent), "волна фолловов не съедает «спасибо» за биты: " + repr(sent))
check(es._follow_greet_allowed(778), "лимит одного канала не трогает другой")
sys.exit(1 if failed else 0)

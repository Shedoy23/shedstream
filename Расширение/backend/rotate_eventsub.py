#!/usr/bin/env python3
"""
rotate_eventsub.py — удалить все EventSub-подписки текущего расширения.

Зачем: после смены EVENTSUB_SECRET в .env старые подписки на стороне Twitch
всё ещё используют старый секрет, поэтому HMAC-проверка в нашем бэке падает.
Удалив подписку и перезапустив бэк, register_eventsub_subscriptions() в
main.py создаст новые подписки (Phase A: channel_points + stream.online/offline)
с новым секретом.

Использование:
    1) Подключись к VPS (или запусти локально с тем же .env).
    2) Перейди в backend: cd /path/to/Расширение/backend
    3) python rotate_eventsub.py
    4) Подтверди удаление (y), потом перезапусти бэк.

Читает TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET из .env.
"""
import asyncio
import os
import sys

import aiohttp
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.getenv("TWITCH_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")

if not (CLIENT_ID and CLIENT_SECRET):
    print("❌ TWITCH_CLIENT_ID или TWITCH_CLIENT_SECRET не заданы в .env")
    sys.exit(1)


async def get_app_token(s: aiohttp.ClientSession) -> str:
    async with s.post(
        "https://id.twitch.tv/oauth2/token",
        data={
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type":    "client_credentials",
        },
    ) as r:
        data = await r.json()
        if r.status != 200:
            raise RuntimeError(f"Не удалось получить app token: HTTP {r.status} {data}")
        return data["access_token"]


async def list_subscriptions(s: aiohttp.ClientSession, token: str) -> list:
    async with s.get(
        "https://api.twitch.tv/helix/eventsub/subscriptions",
        headers={"Client-ID": CLIENT_ID, "Authorization": f"Bearer {token}"},
    ) as r:
        data = await r.json()
        if r.status not in (200, 202):
            raise RuntimeError(f"Не удалось получить список: HTTP {r.status} {data}")
        return data.get("data", [])


async def delete_subscription(s: aiohttp.ClientSession, token: str, sub_id: str) -> int:
    async with s.delete(
        f"https://api.twitch.tv/helix/eventsub/subscriptions?id={sub_id}",
        headers={"Client-ID": CLIENT_ID, "Authorization": f"Bearer {token}"},
    ) as r:
        return r.status


async def main() -> None:
    async with aiohttp.ClientSession() as s:
        print("🔑 Получаю app token...")
        token = await get_app_token(s)

        print("📋 Получаю список EventSub-подписок...")
        subs = await list_subscriptions(s, token)

        if not subs:
            print("✅ Подписок нет — удалять нечего. Перезапусти бэк, он создаст новую.")
            return

        print(f"\nНайдено подписок: {len(subs)}")
        for sub in subs:
            cond = sub.get("condition", {})
            print(
                f"  id={sub['id'][:8]}... "
                f"type={sub['type']} "
                f"status={sub['status']} "
                f"broadcaster={cond.get('broadcaster_user_id', '?')}"
            )

        confirm = input("\nУдалить ВСЕ перечисленные подписки? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Отмена — ничего не удалено.")
            return

        ok = fail = 0
        for sub in subs:
            status = await delete_subscription(s, token, sub["id"])
            mark = "✅" if status == 204 else "❌"
            print(f"  {mark} delete {sub['id'][:8]}... → HTTP {status}")
            if status == 204:
                ok += 1
            else:
                fail += 1

        print(f"\nГотово: удалено {ok}, ошибок {fail}.")
        print("Теперь перезапусти бэк — он зарегистрирует новые подписки с новым EVENTSUB_SECRET.")


if __name__ == "__main__":
    asyncio.run(main())

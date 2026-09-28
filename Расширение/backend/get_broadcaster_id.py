"""
Скрипт для получения broadcaster_id по нику канала.
Запускать на сервере: python3 get_broadcaster_id.py
Требует TWITCH_CLIENT_ID и TWITCH_CLIENT_SECRET в .env
"""
import asyncio
import aiohttp
from dotenv import load_dotenv
import os

load_dotenv()

async def main():
    client_id     = os.getenv('TWITCH_CLIENT_ID', '')
    client_secret = os.getenv('TWITCH_CLIENT_SECRET', '')
    channel_name  = os.getenv('TWITCH_CHANNEL_NAME', '').lower().strip()

    if not client_id or not client_secret:
        print("❌ TWITCH_CLIENT_ID или TWITCH_CLIENT_SECRET не заданы в .env")
        return

    async with aiohttp.ClientSession() as session:
        # Получаем app token
        async with session.post("https://id.twitch.tv/oauth2/token", params={
            "client_id":     client_id,
            "client_secret": client_secret,
            "grant_type":    "client_credentials"
        }) as r:
            data = await r.json()
            token = data.get("access_token")
            if not token:
                print(f"❌ Не удалось получить токен: {data}")
                return

        # Запрашиваем ID по нику
        async with session.get(
            f"https://api.twitch.tv/helix/users?login={channel_name}",
            headers={"Client-ID": client_id, "Authorization": f"Bearer {token}"}
        ) as r:
            data = await r.json()
            users = data.get("data", [])
            if not users:
                print(f"❌ Канал '{channel_name}' не найден")
                return

            user = users[0]
            print(f"\n✅ Найден канал: {user['display_name']}")
            print(f"   Broadcaster ID: {user['id']}")
            print(f"\nДобавь в .env:")
            print(f"TWITCH_BROADCASTER_ID={user['id']}")

asyncio.run(main())

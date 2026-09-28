# -*- coding: utf-8 -*-
"""Каталог RimWorld не должен грузиться, когда стример играет в другую игру.

Во фронте `loadShopCatalog()` стоит БЕЗУСЛОВНО на старте — раньше, чем он вообще
узнаёт активный модуль. Из-за этого каждый зритель Bannerlord-стрима качал
1.6 МБ каталога RimWorld. Фронт заморожен на CDN, поэтому гейт стоит на бэке.

Правила, которые проверяем:
  активный модуль rimworld      → каталог отдаём
  активный модуль другой        → пусто (зритель не платит за чужую игру трафиком)
  модуль не выбран (NULL)       → отдаём (не ломать каналы, где настройку не трогали)
  канала нет / ошибка БД        → отдаём (ведём себя как раньше, не режем молча)

Безопасность переключения обеспечивает фронт: при переходе на вкладку RimWorld
он перезагружает каталог, если тот пуст.

Запуск:  python tests/test_rimworld_catalog_gate.py
"""
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

for k, v in (("TWITCH_OAUTH_TOKEN", "x"), ("TWITCH_CLIENT_ID", "x"),
             ("TWITCH_CLIENT_SECRET", "x"), ("TWITCH_BOT_ID", "x"),
             ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(k, v)

passed = 0
failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print("  OK   %s" % msg)
    else:
        failed += 1
        print("  FAIL %s" % msg)


class FakeDB:
    """Подменяет только get_channel — больше гейту ничего не нужно."""

    def __init__(self, channel):
        self._channel = channel

    async def get_channel(self, channel_id):
        if isinstance(self._channel, Exception):
            raise self._channel
        return self._channel


async def main():
    import rimworld as rw

    cases = [
        ({"active_module": "rimworld"},   True,
         "активен rimworld — каталог отдаём"),
        ({"active_module": "bannerlord"}, False,
         "активен bannerlord — каталог НЕ отдаём (1.6 МБ не летят зрителю)"),
        ({"active_module": "shedcolony"}, False,
         "активен любой другой модуль — тоже не отдаём"),
        ({"active_module": None},         True,
         "модуль не выбран — отдаём (не ломаем ненастроенные каналы)"),
        ({"active_module": "  RimWorld "}, True,
         "регистр и пробелы не ломают распознавание"),
        (None,                            True,
         "канала нет в реестре — отдаём, как раньше"),
        (RuntimeError("БД недоступна"),   True,
         "ошибка БД — отдаём, а не режем молча"),
    ]

    original = rw.get_db
    try:
        for channel, expected, msg in cases:
            rw.get_db = lambda ch=channel: FakeDB(ch)
            got = await rw._rimworld_is_active(98319857)
            check(got is expected, "%s (получили %s)" % (msg, got))
    finally:
        rw.get_db = original

    print("=" * 70)
    print("PASSED: %d   FAILED: %d" % (passed, failed))
    print("ALL GREEN — чужой каталог зрителю не летит." if not failed
          else "КРАСНО — гейт не работает.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

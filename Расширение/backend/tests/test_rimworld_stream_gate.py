# -*- coding: utf-8 -*-
"""RimWorld may bypass Twitch-live without weakening other module gates.

2026-09-11 (постстрим-триаж 10.09) — одно ожидание изменено, и это не
ослабление. Тех-режим (RIMWORLD_REQUIRE_STREAM_LIVE=false) по-прежнему НЕ ходит
в Twitch за статусом эфира — эта часть теста не тронута. Раньше тест ещё
требовал, чтобы в тех-режиме проверка отвечала «можно», ничего не спрашивая.
Ровно это и было дефектом: на проде тех-режим включён, и 10.09 три платных
действия прошли при выключенной игре, а деньги легли в очередь без срока.
Сам переключатель задуман как «прогон С ЗАПУЩЕННОЙ ИГРОЙ» — проверки игры
просто не существовало. Теперь «можно» — только когда игра на связи; без игры
отказ, и в тех-режиме тоже. Требование «без игры — отказ» видели красным на
старом коде: tests/test_rimworld_game_offline_gate.py, случай [6].
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import types
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

CH = 98319857


class FakeBot:
    def __init__(self, live: bool):
        self.live = live
        self.calls = 0

    async def _is_stream_live(self, channel_id=None):
        self.calls += 1
        return self.live


def _game(on_air: bool) -> None:
    """Метка «игра на связи» — тот же кэш module_liveness, что пишет пульс мода."""
    import module_liveness
    module_liveness._cache.pop((CH, "rimworld"), None)
    if on_air:
        module_liveness._cache[(CH, "rimworld")] = time.time()


async def run() -> None:
    import config
    import rimworld

    original_main = sys.modules.get("main")
    original_required = config.RIMWORLD_REQUIRE_STREAM_LIVE
    original_testing = config.TESTING_BYPASS_STREAM_LIVE
    try:
        # db=None: базы у поддельного main нет, метку игры берём из кэша.
        offline_bot = FakeBot(False)
        sys.modules["main"] = types.SimpleNamespace(bot=offline_bot, db=None)
        config.TESTING_BYPASS_STREAM_LIVE = False
        config.RIMWORLD_REQUIRE_STREAM_LIVE = False

        _game(on_air=True)
        assert await rimworld._require_stream_live(channel_id=CH) is None
        assert offline_bot.calls == 0, "RimWorld-only bypass must skip Twitch lookup"

        # 2026-09-11: тех-режим не отменяет проверку игры.
        _game(on_air=False)
        denied = await rimworld._require_stream_live(channel_id=CH)
        assert denied and denied["success"] is False, (
            "тех-режим пропустил платное действие при выключенной игре "
            "(продовый дефект 10.09)")
        assert "игра" in denied["message"].lower()
        assert offline_bot.calls == 0, "проверка игры не должна ходить в Twitch"

        config.RIMWORLD_REQUIRE_STREAM_LIVE = True
        _game(on_air=True)
        denied = await rimworld._require_stream_live(channel_id=CH)
        assert denied and denied["success"] is False
        assert "только во время стрима" in denied["message"]

        online_bot = FakeBot(True)
        sys.modules["main"] = types.SimpleNamespace(bot=online_bot, db=None)
        assert await rimworld._require_stream_live(channel_id=CH) is None
        assert online_bot.calls == 1
    finally:
        config.RIMWORLD_REQUIRE_STREAM_LIVE = original_required
        config.TESTING_BYPASS_STREAM_LIVE = original_testing
        _game(on_air=False)
        if original_main is None:
            sys.modules.pop("main", None)
        else:
            sys.modules["main"] = original_main

    print("ALL GREEN — RimWorld stream gate is independently configurable.")


if __name__ == "__main__":
    asyncio.run(run())

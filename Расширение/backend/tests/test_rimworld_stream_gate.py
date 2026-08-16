# -*- coding: utf-8 -*-
"""RimWorld may bypass Twitch-live without weakening other module gates."""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path


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


class FakeBot:
    def __init__(self, live: bool):
        self.live = live
        self.calls = 0

    async def _is_stream_live(self, channel_id=None):
        self.calls += 1
        return self.live


async def run() -> None:
    import config
    import rimworld

    original_main = sys.modules.get("main")
    original_required = config.RIMWORLD_REQUIRE_STREAM_LIVE
    original_testing = config.TESTING_BYPASS_STREAM_LIVE
    try:
        offline_bot = FakeBot(False)
        sys.modules["main"] = types.SimpleNamespace(bot=offline_bot)
        config.TESTING_BYPASS_STREAM_LIVE = False
        config.RIMWORLD_REQUIRE_STREAM_LIVE = False
        assert await rimworld._require_stream_live(channel_id=98319857) is None
        assert offline_bot.calls == 0, "RimWorld-only bypass must skip Twitch lookup"

        config.RIMWORLD_REQUIRE_STREAM_LIVE = True
        denied = await rimworld._require_stream_live(channel_id=98319857)
        assert denied and denied["success"] is False
        assert "только во время стрима" in denied["message"]

        online_bot = FakeBot(True)
        sys.modules["main"] = types.SimpleNamespace(bot=online_bot)
        assert await rimworld._require_stream_live(channel_id=98319857) is None
        assert online_bot.calls == 1
    finally:
        config.RIMWORLD_REQUIRE_STREAM_LIVE = original_required
        config.TESTING_BYPASS_STREAM_LIVE = original_testing
        if original_main is None:
            sys.modules.pop("main", None)
        else:
            sys.modules["main"] = original_main

    print("ALL GREEN — RimWorld stream gate is independently configurable.")


if __name__ == "__main__":
    asyncio.run(run())

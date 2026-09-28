"""Exercise the production script entrypoint without starting network services."""
import importlib
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")

checked = []

def inspect_startup(app, **kwargs):
    import dependencies
    import rimworld
    running = sys.modules["__main__"]
    original_bot = running.bot
    assert dependencies.get_bot() is original_bot
    # This late import is reached by real RimWorld HTTP requests.
    assert rimworld.get_bot() is original_bot, "RimWorld created a second BotCore"
    assert importlib.import_module("main") is running, "main loaded twice"
    assert dependencies.get_bot() is original_bot, "EventSub bot was replaced"
    assert rimworld.get_db() is running.db
    checked.append(True)

def skip_database_bootstrap(coroutine):
    # Identity check needs module initialization, not migrations or a real DB.
    coroutine.close()

with patch("asyncio.run", side_effect=skip_database_bootstrap), patch("uvicorn.run", side_effect=inspect_startup):
    runpy.run_path(str(BACKEND / "main.py"), run_name="__main__")
assert checked, "production entrypoint was not exercised"
print("PASS: script entrypoint, RimWorld and EventSub share one BotCore")

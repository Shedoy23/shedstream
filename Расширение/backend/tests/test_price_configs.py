"""
test_price_configs.py — цены отдаются клиенту, а не живут копиями во фронте.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_price_configs.py

## Что за дыра

Фронт расширения замерзает на CDN Twitch до следующего ревью (недели), бэкенд
деплоится за минуты. Значит цену можно менять только на сервере, а интерфейс
обязан рисовать то, что сервер прислал. 24.07 копии уже разъезжались: кнопка
удаления черты рисовала 2000💎 при реальных 300.

## Чего требуем

1. /api/core/config отдаёт ядровые числа (голосование, гильдия, развод, TTS).
2. /api/shedcolony/config отдаёт ВЕСЬ словарь цен действий, а не выборку —
   новое действие обязано появляться там само.
3. Значения совпадают с теми, по которым бэкенд реально списывает.

Красный до фикса: эндпоинтов нет вовсе (404) — фронт остаётся на своих копиях.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
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

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else " — " + detail))
    if not ok:
        fails.append(name)


async def main() -> int:
    from config import (
        FAMILY_CONFIG,
        GUILD_CREATE_COST,
        TTS_COST,
        VOTING_MIN_BID,
        VOTING_PROPOSE_MIN_PLEDGE,
    )
    from routes.misc import core_config
    from routes.shedcolony import _ACTION_PRICES, shedcolony_config

    core = await core_config()
    check("минимальная ставка приходит с сервера", core.get("voting_min_bid") == VOTING_MIN_BID)
    check("минимальный вклад приходит с сервера",
          core.get("voting_min_pledge") == VOTING_PROPOSE_MIN_PLEDGE)
    check("цена гильдии приходит с сервера", core.get("guild_create_cost") == GUILD_CREATE_COST)
    check("цена развода приходит с сервера", core.get("divorce_cost") == FAMILY_CONFIG["divorce_cost"])
    check("цена озвучки приходит с сервера", core.get("tts_cost") == TTS_COST)
    presets = core.get("voting_bid_presets") or []
    check("быстрые суммы приходят списком и начинаются с минимума",
          isinstance(presets, list) and presets and presets[0] == VOTING_MIN_BID, str(presets))

    sc = await shedcolony_config()
    prices = sc.get("action_prices") or {}
    check("ShedColony отдаёт словарь цен целиком", prices == _ACTION_PRICES,
          f"{len(prices)} против {len(_ACTION_PRICES)}")
    check("в словаре есть флагманский апгрейд здания",
          prices.get("colony.upgrade_building") == _ACTION_PRICES["colony.upgrade_building"])

    print()
    if fails:
        print(f"ПРОВАЛЕНО: {len(fails)} — " + "; ".join(fails))
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

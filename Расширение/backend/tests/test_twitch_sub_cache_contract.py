"""Standalone regression for the public subscription-tier cache contract."""

from __future__ import annotations

import asyncio
import pathlib
import sys
import time


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


async def main() -> int:
    import twitch_subs

    twitch_subs._SUB_CACHE.clear()
    twitch_subs._SUB_CACHE[(100, "unknown")] = (-1, time.time() + 60)
    twitch_subs._SUB_CACHE[(100, "tier2")] = (2, time.time() + 60)

    unknown = await twitch_subs.get_subscription_tier(100, "unknown")
    tier2 = await twitch_subs.get_subscription_tier(100, "tier2")
    twitch_subs._SUB_CACHE.clear()

    if unknown is not None:
        print(f"FAIL internal -1 sentinel leaked as public tier: {unknown!r}")
        return 1
    if tier2 != 2:
        print(f"FAIL valid cached tier changed: {tier2!r}")
        return 1
    print("ALL GREEN: cached Helix failure returns None; valid tiers stay intact")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

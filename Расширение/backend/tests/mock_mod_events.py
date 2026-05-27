"""
mock_mod_events.py — симулятор mod событий для testing без запуска Bannerlord.

Шлёт fake events на backend's `/v1/module/bannerlord/events` endpoint —
как будто mod connected и пушит updates. Backend обрабатывает их через
обычные event handlers, frontend получает реальные data в UI.

Use case: проверить визуально что extension UI отображает workshops/caravans/
fiefs/heritage panels правильно, БЕЗ запуска игры. Полезно для:
  - Frontend layout testing
  - Race conditions в UI
  - Tooltips / formatting / overflow

Запуск:
    cd Расширение/backend
    set MODULE_TOKEN=your_token_here
    python tests/mock_mod_events.py --channel 1 --host http://localhost:8000

Подкоманды:
    --scenario fresh-hero      Player.linked + state_update
    --scenario passive-income  Workshop + fief + caravan profit sync
    --scenario death-heritage  Player.died → heir activation с inheritance
    --scenario caravan-attack  Caravan destroyed → rescue pool opens
    --scenario all             All scenarios sequentially с pauses

Без MODULE_TOKEN — script откажется работать (HTTP 401 от backend).
Token берётся из `Расширение/backend/.env` или env var.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_USERNAME = "smoke_viewer"
DEFAULT_CHANNEL = 1
DEFAULT_HOST = "http://localhost:8000"


def post_event(host: str, channel_id: int, token: str,
               event_type: str, data: dict, log_label: str = "") -> bool:
    """POST single event envelope. Returns True if backend ACK'd."""
    envelope = {
        "id":   uuid.uuid4().hex,
        "kind": "event",
        "type": event_type,
        "ts":   int(time.time() * 1000),
        "data": data,
    }
    body = json.dumps({
        "channel_id": channel_id,
        "envelopes":  [envelope],
    }).encode("utf-8")

    url = f"{host.rstrip('/')}/v1/module/bannerlord/events"
    req = urlreq.Request(url, data=body, method="POST",
                          headers={
                              "Content-Type":  "application/json",
                              "Authorization": f"Bearer {token}",
                              "User-Agent":    "bannerlord-mock-events/1.0",
                          })
    try:
        with urlreq.urlopen(req, timeout=15.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                resp_json = json.loads(raw)
                ok = (resp_json.get("status") == "ok"
                      or resp_json.get("success") is True)
            except json.JSONDecodeError:
                ok = False
            status_icon = "✅" if ok else "⚠"
            print(f"  {status_icon} [{event_type}] {log_label} → "
                  f"HTTP {resp.status}, response={raw[:200]}")
            return ok
    except HTTPError as he:
        try:
            raw = he.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        print(f"  ❌ [{event_type}] {log_label} → HTTP {he.code}, {raw[:200]}")
        return False
    except URLError as ue:
        print(f"  ❌ [{event_type}] {log_label} → URLError: {ue.reason}")
        return False
    except Exception as ex:
        print(f"  ❌ [{event_type}] {log_label} → {type(ex).__name__}: {ex}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Scenarios
# ─────────────────────────────────────────────────────────────────────────────
def scenario_fresh_hero(host: str, channel: int, token: str, username: str):
    """Player.linked — fresh hero adoption."""
    print(f"\n[Scenario] fresh-hero: @{username} joins, becomes [BLink]")
    post_event(host, channel, token, "player.linked", {
        "username":     username,
        "hero_id":      f"mock_hero_{username}_{int(time.time())}",
        "display_name": username,
        "culture":      "vlandia",
    }, log_label=f"@{username}")
    post_event(host, channel, token, "player.state_update", {
        "username":   username,
        "hero_id":    f"mock_hero_{username}",
        "gold":       50000,
        "level":      5,
        "kingdom_name": "Vlandia",
        "is_alive":   1,
    }, log_label=f"@{username} initial state")


def scenario_passive_income(host: str, channel: int, token: str, username: str):
    """Symbol passive income trilogy (workshop + fief + caravan profit sync).
    Requires user уже has rows в соответствующих таблицах
    (либо create_caravan/buy_workshop через UI first)."""
    print(f"\n[Scenario] passive-income: 3 sync events для @{username}")
    post_event(host, channel, token, "hero.workshop_profit_sync", {
        "owner":          username,
        "settlement_id":  "town_V1",     # Pravend
        "workshop_type":  "smithy",
        "net_dinars":     800,            # → 8⦷ credit (100:1)
        "capital_now":    15800,
    }, log_label="Smithy/Pravend +800 din")
    post_event(host, channel, token, "hero.fief_tribute_sync", {
        "owner":      username,
        "fief_id":    "town_V2",         # Sargot
        "fief_name":  "Sargot",
        "fief_type":  "town",
        "net_dinars": 1200,                # → 6⦷ credit (200:1)
    }, log_label="Sargot fief +1200 din")
    post_event(host, channel, token, "hero.caravan_profit_sync", {
        "owner":      username,
        "party_id":   f"mock_caravan_{username}",
        "net_dinars": 600,                 # → 4⦷ credit (150:1)
    }, log_label="Caravan +600 din")


def scenario_death_heritage(host: str, channel: int, token: str, username: str):
    """Player.died — triggers heir activation + HERITAGE asset transfer.
    Requires виewer уже has heir в bannerlord_heirs (came_of_age event)."""
    print(f"\n[Scenario] death-heritage: @{username} dies, heir inherits empire")
    post_event(host, channel, token, "player.died", {
        "username":    username,
        "killer_name": "MockBandit",
        "battle_id":   "mock_battle_1",
    }, log_label=f"@{username} killed")


def scenario_caravan_attack(host: str, channel: int, token: str, username: str):
    """Caravan destroyed → backend opens rescue pool."""
    print(f"\n[Scenario] caravan-attack: @{username}'s caravan destroyed")
    post_event(host, channel, token, "hero.caravan_destroyed", {
        "owner":       username,
        "party_id":    f"mock_caravan_{username}",
        "captor_name": "Looters Band #3",
    }, log_label=f"Caravan destroyed by Looters")


def scenario_heir_lifecycle(host: str, channel: int, token: str, username: str):
    """heir.came_of_age — viewer ребёнок взрослеет."""
    print(f"\n[Scenario] heir-lifecycle: @{username} child comes of age")
    post_event(host, channel, token, "hero.heir_came_of_age", {
        "parent_username": username,
        "heir_hero_id":    f"mock_heir_{username}_{int(time.time())}",
        "heir_name":       f"Heir_{username}",
    }, log_label=f"@{username}'s child grew up")


SCENARIOS = {
    "fresh-hero":       scenario_fresh_hero,
    "passive-income":   scenario_passive_income,
    "death-heritage":   scenario_death_heritage,
    "caravan-attack":   scenario_caravan_attack,
    "heir-lifecycle":   scenario_heir_lifecycle,
}


def scenario_all(host: str, channel: int, token: str, username: str):
    """All scenarios sequentially с pauses."""
    print(f"\n[Scenario] all — running 5 scenarios для @{username}")
    for name, fn in SCENARIOS.items():
        if name == "fresh-hero":
            fn(host, channel, token, username)
            time.sleep(1)
        elif name == "heir-lifecycle":
            fn(host, channel, token, username)
            time.sleep(1)
        elif name == "passive-income":
            fn(host, channel, token, username)
            time.sleep(1)
        elif name == "caravan-attack":
            fn(host, channel, token, username)
            time.sleep(1)
        elif name == "death-heritage":
            fn(host, channel, token, username)
            time.sleep(1)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"Backend URL (default {DEFAULT_HOST})")
    parser.add_argument("--channel", type=int, default=DEFAULT_CHANNEL,
                        help=f"channel_id (default {DEFAULT_CHANNEL})")
    parser.add_argument("--username", default=DEFAULT_USERNAME,
                        help=f"viewer username (default '{DEFAULT_USERNAME}')")
    parser.add_argument("--token", default=os.environ.get("MODULE_TOKEN"),
                        help="Module bearer token (или env MODULE_TOKEN)")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()) + ["all"],
                        default="all",
                        help="Which scenario to run (default 'all')")
    args = parser.parse_args()

    if not args.token:
        print("❌ No --token provided + no MODULE_TOKEN env var.")
        print("   Get module token: SELECT token FROM module_tokens WHERE module_id='bannerlord' AND channel_id=N;")
        print("   Set: export MODULE_TOKEN=... (Linux) или set MODULE_TOKEN=... (Windows)")
        sys.exit(2)

    print(f"\n{'=' * 70}")
    print(f"Mock mod events → backend {args.host}")
    print(f"  channel_id={args.channel}  username='{args.username}'  scenario={args.scenario}")
    print(f"{'=' * 70}")

    if args.scenario == "all":
        scenario_all(args.host, args.channel, args.token, args.username)
    else:
        SCENARIOS[args.scenario](args.host, args.channel, args.token, args.username)

    print(f"\n{'=' * 70}")
    print(f"Scenarios done. Открой extension UI / frontend для проверки UI rendering.")
    print(f"Backend logs покажут: log.info '[SHOP-SYNC]' / '[FIEF-SYNC]' / '[CARAVAN-SYNC]' / [HEIR-ACTIVATE]")


if __name__ == "__main__":
    main()

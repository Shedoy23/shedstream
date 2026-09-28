"""Bounded, reloadable Bannerlord UI settings for the reviewed Twitch client.

The override lives outside backend/frontend deploy archives. It can reorder or
hide components already shipped in the ZIP, but cannot define new code/actions.
"""
import json
import os
import re
from pathlib import Path


SECTIONS = ("summon", "active_powers", "tournament", "weapon_choice")
LABELS = {
    "active_powers": "Активки",
    "tournament": "🏆 Турнир зрителей",
    "weapon_choice": "Оружейная способность",
    "summon_ally": "📯 Призвать за стримера",
    "summon_enemy": "⚔️ Призвать против стримера",
    "discard": "🗑 Выкинуть вещь",
}
TIER_COLORS = {
    "1": {"text": "#c0c3ca", "border": "#5b5e66", "background": "#2b2d31"},
    "2": {"text": "#89dba1", "border": "#467457", "background": "#203127"},
    "3": {"text": "#87c6fa", "border": "#426c91", "background": "#202d3a"},
    "4": {"text": "#c7a0f5", "border": "#785398", "background": "#30253b"},
    "5": {"text": "#f2b17f", "border": "#966139", "background": "#3b2b20"},
    "6": {"text": "#f5d174", "border": "#aa8436", "background": "#39311e"},
}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "bannerlord_ui_config.json"


def config_path():
    return Path(os.environ.get("BANNERLORD_UI_CONFIG_PATH") or DEFAULT_PATH)


def load_ui_config():
    """Read every request so an operator can update presentation without a deploy."""
    settings = {"version": 1, "combat_order": list(SECTIONS),
                "combat_visible": {section: True for section in SECTIONS},
                "labels": dict(LABELS),
                "tier_colors": {tier: dict(colors) for tier, colors in TIER_COLORS.items()}}
    try:
        path = config_path()
        if path.stat().st_size > 16384:
            return settings
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return settings
    if not isinstance(raw, dict) or type(raw.get("version")) is not int or raw["version"] != 1:
        return settings

    order = raw.get("combat_order")
    if isinstance(order, list) and len(order) == len(SECTIONS) and all(isinstance(x, str) for x in order) and set(order) == set(SECTIONS):
        settings["combat_order"] = order
    visible = raw.get("combat_visible")
    if isinstance(visible, dict):
        for section in SECTIONS:
            if type(visible.get(section)) is bool:
                settings["combat_visible"][section] = visible[section]
    labels = raw.get("labels")
    if isinstance(labels, dict):
        for key in LABELS:
            value = labels.get(key)
            if isinstance(value, str) and 1 <= len(value) <= 64 and value.isprintable():
                settings["labels"][key] = value
    palette = raw.get("tier_colors")
    if isinstance(palette, dict):
        for tier in TIER_COLORS:
            entry = palette.get(tier)
            if not isinstance(entry, dict):
                continue
            for token in ("text", "border", "background"):
                value = entry.get(token)
                if isinstance(value, str) and COLOR_RE.fullmatch(value):
                    settings["tier_colors"][tier][token] = value.lower()
    return settings

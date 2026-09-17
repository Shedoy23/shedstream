"""UI tuning is data-only, bounded and reloadable without a backend restart."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.bannerlord.ui_config import load_ui_config


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "bannerlord_ui_config.json"
        with patch.dict(os.environ, {"BANNERLORD_UI_CONFIG_PATH": str(path)}):
            default = load_ui_config()
            assert default["version"] == 1
            assert default["combat_order"] == ["summon", "active_powers", "tournament", "weapon_choice"]
            assert default["tier_colors"]["6"]["text"] == "#f5d174"

            path.write_text(json.dumps({"version": 1,
                "combat_order": ["tournament", "summon", "active_powers", "weapon_choice"],
                "combat_visible": {"tournament": False, "unknown": False},
                "labels": {"tournament": "Арена недели", "active_powers": "⚡ Быстрые действия"},
                "tier_colors": {"6": {"text": "#ABCDEF"}}}), encoding="utf-8")
            changed = load_ui_config()
            assert changed["combat_order"][0] == "tournament"
            assert not changed["combat_visible"]["tournament"]
            assert changed["labels"]["tournament"] == "Арена недели"
            assert changed["tier_colors"]["6"]["text"] == "#abcdef"
            assert changed["tier_colors"]["6"]["border"] == default["tier_colors"]["6"]["border"]

            path.write_text(json.dumps({"version": 1,
                "combat_order": ["summon", "summon", "tournament", "weapon_choice"],
                "combat_visible": {"summon": "false"},
                "labels": {"tournament": "bad\nlabel", "unknown": "new action"},
                "tier_colors": {"6": {"text": "url(javascript:alert(1))"}}}), encoding="utf-8")
            invalid = load_ui_config()
            assert invalid["combat_order"] == default["combat_order"]
            assert invalid["combat_visible"]["summon"] is True
            assert invalid["labels"]["tournament"] == default["labels"]["tournament"]
            assert invalid["tier_colors"]["6"]["text"] == default["tier_colors"]["6"]["text"]

            path.write_text(json.dumps({"version": 1, "combat_order": [{}, 1]}), encoding="utf-8")
            assert load_ui_config() == default  # Malformed nested values cannot crash /config.
            path.write_text(json.dumps({"version": 2, "labels": {"tournament": "future"}}), encoding="utf-8")
            assert load_ui_config() == default
            path.write_text(" " * 16385, encoding="utf-8")
            assert load_ui_config() == default

    print("PASS: Bannerlord UI defaults, live file reload, allowed fields, malformed/unknown settings and size cap")


if __name__ == "__main__":
    main()

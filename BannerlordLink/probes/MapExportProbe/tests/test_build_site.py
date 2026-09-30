"""Offline check of build-site.py: the page's linear transform must match world_to_pixel. Exit 0 = ok."""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("build_site", os.path.join(HERE, "..", "build-site.py"))
build_site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_site)

failures = 0


def check(condition, label):
    global failures
    print(("PASS " if condition else "FAIL ") + label)
    if not condition:
        failures += 1


W, H = 6, 5
report = {
    "attemptUtc": "t",
    "campaignBounds": {"min": [62, 30], "max": [790, 640]},
    "terrainGrid": {"width": W, "height": H, "surface": ["Plain"] * (W * H), "terrainHeight": [None] * (W * H)},
    "settlements": [{"id": "town_A", "name": "A", "kind": "town", "xy": [100, 600], "factionColor": "#123456"},
                    {"id": "v1", "name": "V", "kind": "village", "xy": [700, 40], "bound": "town_A"}],
    "factions": [{"id": "k", "name": "K", "color": "#ABCDEF"}, {"id": "gone", "eliminated": True}],
}
image, data = build_site.site_data(report)
t = data["transform"]
worst = 0.0
for xy in ([62, 30], [790, 640], [100, 600], [700, 40], [426, 335]):
    px, py = build_site.render_map.world_to_pixel(report, xy)
    worst = max(worst, abs(t["ax"] * xy[0] + t["bx"] - px), abs(t["ay"] * xy[1] + t["by"] - py))
check(worst < 1e-6, "live-party transform reproduces world_to_pixel (max error %.2e px)" % worst)
check(t["ay"] < 0, "higher world Y is higher on the page (Y flipped)")
town = next(s for s in data["settlements"] if s["id"] == "town_A")
check(abs(town["x"] - (t["ax"] * 100 + t["bx"])) < 0.1, "static settlements and live parties share one coordinate frame")
village = next(s for s in data["settlements"] if s["id"] == "v1")
check(village["boundName"] == "A", "village names its town")
check([f["id"] for f in data["factions"]] == ["k"], "eliminated kingdoms are not listed")
print(f"failures {failures}")
sys.exit(1 if failures else 0)

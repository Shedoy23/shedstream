"""Offline check of render-map.py on a synthetic probe.json. Exit 0 = ok."""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("render_map", os.path.join(HERE, "..", "render-map.py"))
render_map = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_map)

failures = 0


def check(condition, label):
    global failures
    print(("PASS " if condition else "FAIL ") + label)
    if not condition:
        failures += 1


# 4x3 grid over x 0..30, y 0..20: bottom row sea, top-right node forest, rest plain.
W, H = 4, 3
surface = ["sea:OpenSea"] * W + ["Plain"] * W + ["Plain", "Plain", "Plain", "Forest"]
report = {
    "status": "data_complete_geography_unverified",
    "campaignBounds": {"min": [0, 0], "max": [30, 20]},
    "terrainGrid": {"width": W, "height": H, "surface": surface, "terrainHeight": [None] * (W * H)},
    "settlements": [{"id": "town_A", "name": "A", "kind": "town", "xy": [0, 20], "factionColor": "#FF0000"}],
}
img = render_map.render(report)
C = render_map.CELL
check(img.size == (W * C, H * C), "one cell per grid node")
check(img.getpixel((C // 2 + C, H * C - 2)) == render_map.SURFACE_COLORS["OpenSea"],
      "row 0 (lowest world Y) is drawn at the bottom of the picture")
check(img.getpixel((W * C - 1, 0)) == render_map.SURFACE_COLORS["Forest"],
      "top-right world node lands in the top-right corner")
check(img.getpixel((C // 2, C // 2)) == (255, 0, 0), "settlement drawn in its faction colour at its world position")

broken = dict(report, terrainGrid=dict(report["terrainGrid"], surface=surface[:-1]))
try:
    render_map.render(broken)
    check(False, "incomplete grid is refused, not drawn shifted")
except ValueError:
    check(True, "incomplete grid is refused, not drawn shifted")

print(f"failures {failures}")
sys.exit(1 if failures else 0)

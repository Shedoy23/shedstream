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

check(render_map.surface_color(None, 0.2) == render_map.SURFACE_COLORS["OpenSea"],
      "no navmesh at sea level is drawn as sea (first real export: 2471 such nodes)")
check(render_map.surface_color(None, 6.0) == render_map.IMPASSABLE,
      "no navmesh on high ground is drawn as impassable rock, not sea")
check(render_map.surface_color(None, None) == render_map.NO_DATA, "no navmesh and no height stays 'no data'")

# Smooth website terrain: same frame as world_to_pixel(cell=f), sea stays sea, land stays land.
SW, SH = 8, 6
smooth_report = {
    "campaignBounds": {"min": [0, 0], "max": [70, 50]},
    "terrainGrid": {"width": SW, "height": SH,
                    "surface": (["sea:OpenSea"] * 4 + ["Plain"] * 4) * SH, "terrainHeight": [0.0] * (SW * SH)},
}
sm = render_map.render_smooth(smooth_report)
f = render_map.smooth_factor(SW)
check(sm.size == (SW * f, SH * f), "smooth picture is grid x factor (%dx%d)" % sm.size)
sea_px = sm.getpixel(render_map.world_to_pixel(smooth_report, [10, 25], f))
land_px = sm.getpixel(render_map.world_to_pixel(smooth_report, [60, 25], f))
check(sea_px[2] > sea_px[1] and sea_px[2] > sea_px[0], "sea node stays blue after smoothing %s" % (sea_px,))
check(land_px[1] > land_px[2], "land node stays green after smoothing %s" % (land_px,))

broken = dict(report, terrainGrid=dict(report["terrainGrid"], surface=surface[:-1]))
try:
    render_map.render(broken)
    check(False, "incomplete grid is refused, not drawn shifted")
except ValueError:
    check(True, "incomplete grid is refused, not drawn shifted")

print(f"failures {failures}")
sys.exit(1 if failures else 0)

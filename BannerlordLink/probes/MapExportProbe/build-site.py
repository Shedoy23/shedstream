"""Turn probe.json into the two files the website map page serves.

    python build-site.py <probe.json> <out_dir>

out_dir/terrain.png  - terrain picture without settlements (the page draws them)
out_dir/map.json     - settlements in picture pixels + factions, schema shedlink.campaign-map.v1

Upload both to <CAMPAIGN_MAP_DIR>/<channel_id>/ on the server; the page is
https://shedoy23.ru/map/<login>.
"""
import importlib.util
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("render_map", os.path.join(_HERE, "render-map.py"))
render_map = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_map)

KINDS = ("town", "castle", "village", "hideout")


def site_data(report):
    image = render_map.render(report, settlements_layer=False)
    by_id = {s["id"]: s for s in report.get("settlements", [])}
    settlements = []
    for s in report.get("settlements", []):
        if s.get("kind") not in KINDS or not s.get("xy"):
            continue
        x, y = render_map.world_to_pixel(report, s["xy"])
        bound = by_id.get(s.get("bound") or "")
        settlements.append({
            "id": s["id"], "name": s.get("name") or s["id"], "kind": s["kind"],
            "x": round(x, 1), "y": round(y, 1),
            "factionId": s.get("factionId"), "factionName": s.get("factionName"),
            "color": s.get("factionColor") or "#ffffff", "clanName": s.get("clanName"),
            "boundName": bound.get("name") if bound else None,
        })
    factions = [{"id": f["id"], "name": f.get("name") or f["id"], "color": f.get("color") or "#ffffff"}
                for f in report.get("factions", []) if not f.get("eliminated")]
    data = {
        "schema": "shedlink.campaign-map.v1",
        "exportedUtc": report.get("attemptUtc"),
        "image": {"width": image.width, "height": image.height, "file": "terrain.png"},
        "factions": factions,
        "settlements": settlements,
    }
    return image, data


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        report = json.load(f)
    image, data = site_data(report)
    os.makedirs(argv[2], exist_ok=True)
    image.save(os.path.join(argv[2], "terrain.png"))
    with open(os.path.join(argv[2], "map.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"site files: {argv[2]} ({len(data['settlements'])} settlements, {image.width}x{image.height})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

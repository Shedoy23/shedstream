"""Draw a campaign map picture from probe.json (map-data-grid.v4). No game, no renderer.

    python render-map.py <probe.json> [out.png]

The picture is built only from exported data: navmesh surface per grid node,
terrain height for relief, settlements with their faction colours. World Y grows
up, image Y grows down, so rows are flipped here (the probe never flips).
"""
import json
import sys

from PIL import Image, ImageDraw

CELL = 8  # pixels per grid node

# TerrainType names from the navmesh; unknown names fall back to grey.
SURFACE_COLORS = {
    "Plain": (148, 170, 96), "RuralArea": (160, 176, 104), "Steppe": (190, 184, 120),
    "Desert": (222, 200, 140), "Dune": (230, 208, 150), "Canyon": (184, 140, 100),
    "Forest": (72, 116, 64), "Swamp": (96, 118, 88), "Mountain": (128, 116, 104),
    "Snow": (236, 238, 242), "Beach": (226, 214, 164), "Fording": (120, 160, 170),
    "Bridge": (140, 120, 96), "River": (72, 128, 184), "Lake": (64, 118, 176),
    "Water": (56, 104, 164), "CoastalSea": (70, 120, 180), "OpenSea": (44, 88, 150),
}
NO_DATA = (30, 36, 48)
UNKNOWN = (150, 150, 150)
SEA = (50, 96, 160)
SETTLEMENT_RADIUS = {"town": 7, "castle": 5, "village": 3, "hideout": 2}


def surface_color(name):
    if name is None:
        return NO_DATA
    if name.startswith("sea:"):
        return SURFACE_COLORS.get(name[4:], SEA)
    return SURFACE_COLORS.get(name, UNKNOWN)


def hex_rgb(value, fallback=(255, 255, 255)):
    try:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    except (TypeError, ValueError, IndexError):
        return fallback


def shade(color, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def render(report):
    grid = report["terrainGrid"]
    width, height = grid["width"], grid["height"]
    surface = grid["surface"]
    heights = grid.get("terrainHeight") or [None] * len(surface)
    if len(surface) != width * height:
        raise ValueError(f"grid incomplete: {len(surface)} of {width * height} samples "
                         f"(status {report.get('status')})")
    image = Image.new("RGB", (width * CELL, height * CELL), NO_DATA)
    draw = ImageDraw.Draw(image)
    for row in range(height):
        for col in range(width):
            i = row * width + col
            color = surface_color(surface[i])
            # Relief: light from the west, brighter where terrain rises to the east.
            h, west = heights[i], heights[i - 1] if col > 0 else None
            if h is not None and west is not None and surface[i] and not surface[i].startswith("sea:"):
                color = shade(color, 1 + max(-0.25, min(0.25, (h - west) * 0.05)))
            top = (height - 1 - row) * CELL  # flip: world Y up
            draw.rectangle([col * CELL, top, col * CELL + CELL - 1, top + CELL - 1], fill=color)

    (min_x, min_y), (max_x, max_y) = report["campaignBounds"]["min"], report["campaignBounds"]["max"]

    def to_pixel(xy):
        px = (xy[0] - min_x) / (max_x - min_x) * (width - 1) * CELL + CELL / 2
        py = (height - 1 - (xy[1] - min_y) / (max_y - min_y) * (height - 1)) * CELL + CELL / 2
        return px, py

    settlements = sorted(report.get("settlements", []),
                         key=lambda s: SETTLEMENT_RADIUS.get(s.get("kind"), 2))
    for s in settlements:
        x, y = to_pixel(s["xy"])
        r = SETTLEMENT_RADIUS.get(s.get("kind"), 2)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=hex_rgb(s.get("factionColor")), outline=(20, 20, 20))
    for s in settlements:
        if s.get("kind") == "town" and s.get("name"):
            x, y = to_pixel(s["xy"])
            draw.text((x + 9, y - 6), s["name"], fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
    return image


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        report = json.load(f)
    out = argv[2] if len(argv) == 3 else argv[1].rsplit(".", 1)[0] + ".png"
    render(report).save(out)
    print(f"map: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Draw a campaign map picture from probe.json (map-data-grid.v4). No game, no renderer.

    python render-map.py <probe.json> [out.png]

The picture is built only from exported data: navmesh surface per grid node,
terrain height for relief, settlements with their faction colours. World Y grows
up, image Y grows down, so rows are flipped here (the probe never flips).
"""
import json
import sys

from PIL import Image, ImageDraw, ImageFont

CELL = 8  # max pixels per grid node
TARGET_WIDTH = 1536  # dense grids get smaller cells so the picture stays ~1.5k px wide


def cell_size(width):
    return max(2, min(CELL, round(TARGET_WIDTH / width)))

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
# No navmesh at a node = open sea or impassable land. The first real export (30.09,
# Calradia) splits them by terrain height: sea sits at 0..1, impassable ridges above.
SEA_LEVEL = 1.5
IMPASSABLE = (92, 84, 78)
SETTLEMENT_RADIUS = {"town": 7, "castle": 5, "village": 3, "hideout": 2}


def surface_color(name, height=None):
    if name is None:
        if height is None:
            return NO_DATA
        return SURFACE_COLORS["OpenSea"] if height < SEA_LEVEL else IMPASSABLE
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


def world_to_pixel(report, xy, cell=None):
    """Campaign coordinates -> picture pixel (centre of the node's cell, Y flipped)."""
    grid = report["terrainGrid"]
    width, height = grid["width"], grid["height"]
    (min_x, min_y), (max_x, max_y) = report["campaignBounds"]["min"], report["campaignBounds"]["max"]
    c = cell or cell_size(width)
    px = (xy[0] - min_x) / (max_x - min_x) * (width - 1) * c + c / 2
    py = (height - 1 - (xy[1] - min_y) / (max_y - min_y) * (height - 1)) * c + c / 2
    return px, py


def render(report, settlements_layer=True):
    grid = report["terrainGrid"]
    width, height = grid["width"], grid["height"]
    surface = grid["surface"]
    heights = grid.get("terrainHeight") or [None] * len(surface)
    if len(surface) != width * height:
        raise ValueError(f"grid incomplete: {len(surface)} of {width * height} samples "
                         f"(status {report.get('status')})")
    c = cell_size(width)
    bounds = report["campaignBounds"]
    spacing = (bounds["max"][0] - bounds["min"][0]) / max(1, width - 1)  # world units between nodes
    image = Image.new("RGB", (width * c, height * c), NO_DATA)
    draw = ImageDraw.Draw(image)
    for row in range(height):
        for col in range(width):
            i = row * width + col
            color = surface_color(surface[i], heights[i])
            # Relief: light from the west, brighter where terrain rises to the east.
            h, west = heights[i], heights[i - 1] if col > 0 else None
            if h is not None and west is not None and surface[i] and not surface[i].startswith("sea:"):
                # Slope, not raw height step: a denser grid must not flatten the relief.
                slope = (h - west) / spacing
                color = shade(color, 1 + max(-0.25, min(0.25, slope * 0.38)))
            top = (height - 1 - row) * c  # flip: world Y up
            draw.rectangle([col * c, top, col * c + c - 1, top + c - 1], fill=color)

    if not settlements_layer:
        return image  # the website draws settlements itself, interactively

    def to_pixel(xy):
        return world_to_pixel(report, xy)

    settlements = sorted(report.get("settlements", []),
                         key=lambda s: SETTLEMENT_RADIUS.get(s.get("kind"), 2))
    for s in settlements:
        x, y = to_pixel(s["xy"])
        r = SETTLEMENT_RADIUS.get(s.get("kind"), 2)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=hex_rgb(s.get("factionColor")), outline=(20, 20, 20))
    try:  # PIL's built-in font has no Cyrillic; Arial is on every Windows box
        font = ImageFont.truetype("arial.ttf", 12)
    except OSError:
        font = ImageFont.load_default()
    for s in settlements:
        if s.get("kind") == "town" and s.get("name"):
            x, y = to_pixel(s["xy"])
            draw.text((x + 9, y - 6), s["name"], fill=(255, 255, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
    return image


# ---------- smooth "cartographic" terrain for the website ----------
SMOOTH_WIDTH = 2048  # target picture width; any grid density is upscaled to about this
# Rivers are one node wide at best: as mask water they turn into chains of blobs, so they
# stay land and tint it blue instead.
WATER_TYPES = {"Water", "Lake", "OpenSea", "CoastalSea"}
DEEP_SEA = (38, 78, 138)
SHALLOW_SEA = (78, 132, 186)


def smooth_factor(width):
    return max(2, round(SMOOTH_WIDTH / width))


def is_water(surface, height):
    if surface is None:
        return height is not None and height < SEA_LEVEL
    return surface.startswith("sea:") or surface in WATER_TYPES


def render_smooth(report):
    """Terrain without the grid look: node colours and heights are bicubic-upscaled,
    coastlines come from a smoothed water mask, relief is a hillshade of the smoothed
    heights. Pixel (i*f + f/2) is node i's centre, same frame as world_to_pixel(cell=f)."""
    import numpy as np

    grid = report["terrainGrid"]
    width, height = grid["width"], grid["height"]
    surface = grid["surface"]
    heights = grid.get("terrainHeight") or [None] * len(surface)
    if len(surface) != width * height:
        raise ValueError(f"grid incomplete: {len(surface)} of {width * height} samples "
                         f"(status {report.get('status')})")
    color = np.zeros((height, width, 3), np.float32)
    water = np.zeros((height, width), np.float32)
    elev = np.zeros((height, width), np.float32)
    for row in range(height):
        r = height - 1 - row  # flip: world Y up
        for col in range(width):
            i = row * width + col
            s, h = surface[i], heights[i]
            elev[r, col] = h if h is not None else 0.0
            if is_water(s, h):
                water[r, col] = 1.0
            else:
                color[r, col] = surface_color(s, h)

    # Land colour under the sea is filled from land neighbours, so upscaling does not
    # bleed blue into the shore; the water mask decides where the sea actually is.
    known = water < 0.5
    for _ in range(64):
        if known.all():
            break
        acc = np.zeros_like(color)
        cnt = np.zeros((height, width), np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            shifted_known = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(color, (dy, dx), (0, 1)) * shifted_known[..., None]
            cnt += shifted_known
        grow = (~known) & (cnt > 0)
        color[grow] = acc[grow] / cnt[grow][:, None]
        known = known | grow

    f = smooth_factor(width)
    size = (width * f, height * f)

    def up(a):
        return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize(size, Image.BICUBIC))

    from PIL import ImageFilter
    blur = ImageFilter.GaussianBlur(radius=f * 0.45)  # hides the node grid in colour patches

    def up_soft(a):
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "L").resize(size, Image.BICUBIC).filter(blur)
        return np.asarray(im).astype(np.float32)  # colour channels: 8 bits are plenty

    land = np.stack([up_soft(color[..., k]) for k in range(3)], -1)
    wmask = np.clip(up(water), 0, 1)
    hh = up(elev)

    # Hillshade, light from the north-west. Slope is per world unit, so density does not matter.
    bounds = report["campaignBounds"]
    spacing = (bounds["max"][0] - bounds["min"][0]) / max(1, width - 1) / f
    gy, gx = np.gradient(hh, spacing)
    shade_map = 1 + np.clip((gx + gy) * 0.3, -0.35, 0.35)
    land = land * shade_map[..., None]

    # Sea: lighter near the shore, deeper away from it.
    depth = np.clip((wmask - 0.5) * 2, 0, 1)[..., None]
    sea = np.array(SHALLOW_SEA, np.float32) * (1 - depth) + np.array(DEEP_SEA, np.float32) * depth
    alpha = np.clip((wmask - 0.5) * 6 + 0.5, 0, 1)[..., None]  # crisp but anti-aliased coast
    out = land * (1 - alpha) + sea * alpha
    coast = np.clip(1 - np.abs(wmask - 0.5) * 12, 0, 1)[..., None]  # thin dark shoreline
    out = out * (1 - 0.35 * coast)
    rng = np.random.default_rng(7)  # faint grain against banding in flat areas
    out += rng.normal(0, 1.6, out.shape[:2])[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


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

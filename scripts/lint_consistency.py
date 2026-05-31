#!/usr/bin/env python3
"""
lint_consistency.py — cheap project-wide consistency checks.

Encodes the exact drift classes we have hit by hand:
  HARD (exit 1):
    * viewer.js?v= cache-bust must match across extension.html & mobile.html
      (desync = part of the audience runs stale JS).
    * every backend/migrations/m*.py must be wired into main.py run_migrations
      (an unwired migration silently never applies on deploy).
  SOFT (warn, exit 0):
    * manifest hero.*/power.* actions should be referenced somewhere in the
      backend (drift = action silently dead).
    * crustic currency glyph split in viewer.js (the gem-emoji vs unit-glyph
      inconsistency — informational until unified).

Output is ASCII-only (safe on a cp1251 Windows console). Run from anywhere:
    python scripts/lint_consistency.py
"""
import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
# extension dir = the one containing backend/ (avoids hardcoding Cyrillic name)
EXT = next((p for p in ROOT.iterdir() if (p / "backend").is_dir()), None)

errors: list[str] = []
warns: list[str] = []


def check_version_sync():
    fe = EXT / "frontend"
    found = {}
    for h in ("extension.html", "mobile.html"):
        p = fe / h
        if not p.exists():
            continue
        m = re.search(r"viewer\.js\?v=([^\"']+)", p.read_text(encoding="utf-8"))
        if m:
            found[h] = m.group(1)
    if len(set(found.values())) > 1:
        errors.append(f"viewer.js cache-bust DESYNC across html: {found}")


def check_migrations_wired():
    mig = EXT / "backend" / "migrations"
    main = (EXT / "backend" / "main.py").read_text(encoding="utf-8")
    missing = [f.stem for f in sorted(mig.glob("m*.py")) if f.stem not in main]
    if missing:
        errors.append(
            "migrations present but NOT wired in main.py run_migrations(): "
            + ", ".join(missing)
        )


def _manifest_action_names(text: str) -> list[str]:
    """Collect only items under `actions:` blocks (top-level + nested under
    extensions:). Avoids false-positives from `events:` blocks, which share
    the `- hero.X` syntax."""
    names, mode, mode_indent = [], None, -1
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        item = re.match(r"-\s+(\S+)", s)
        if item:
            if mode == "actions":
                names.append(item.group(1))
            continue
        key = re.match(r"(\w+):", s)
        if key:
            if key.group(1) in ("actions", "events"):
                mode, mode_indent = key.group(1), indent
            elif indent <= mode_indent:
                mode = None
    return names


def check_manifest_actions():
    man = EXT / "backend" / "modules" / "bannerlord" / "manifest.yaml"
    if not man.exists():
        return
    actions = _manifest_action_names(man.read_text(encoding="utf-8"))
    hay = ""
    for rel in (
        "routes/bannerlord.py",
        "routes/bannerlord_family.py",
        "routes/bannerlord_admin.py",
        "modules/bannerlord/_adapter.py",
    ):
        p = EXT / "backend" / rel
        if p.exists():
            hay += p.read_text(encoding="utf-8")
    orphan = sorted({a for a in actions if a not in hay})
    if orphan:
        warns.append(
            "manifest actions not referenced in backend (possible drift): "
            + ", ".join(orphan)
        )


def check_currency_glyph():
    p = EXT / "frontend" / "viewer.js"
    if not p.exists():
        return
    js = p.read_text(encoding="utf-8")
    n_unit = js.count("⦷")   # U+29B7 crustic unit glyph
    n_gem = js.count("\U0001f48e")  # gem emoji
    if n_unit and n_gem:
        warns.append(
            f"two crustic glyphs in viewer.js: unit-glyph x{n_unit}, "
            f"gem-emoji x{n_gem} (consider unifying for clarity)"
        )


def main() -> int:
    if EXT is None:
        print("[lint] FAIL: could not locate extension dir (with backend/)")
        return 1
    for fn in (check_version_sync, check_migrations_wired,
               check_manifest_actions, check_currency_glyph):
        try:
            fn()
        except Exception as e:  # a broken check shouldn't crash CI silently
            warns.append(f"{fn.__name__} could not run: {type(e).__name__}: {e}")

    for w in warns:
        print(f"[lint][warn] {w}")
    for e in errors:
        print(f"[lint][ERROR] {e}")

    if errors:
        print(f"[lint] FAILED: {len(errors)} error(s), {len(warns)} warning(s)")
        return 1
    print(f"[lint] OK ({len(warns)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())

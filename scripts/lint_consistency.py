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
import ast
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


# ---------------------------------------------------------------------------
# Tenant-scoping gate (the project's #1 recurring bug class).
#
# Every query on a channel_id-scoped table MUST reference channel_id, or it
# leaks / merges data across streamers. Marriages, TTS, and rimworld-sync all
# shipped unscoped and were caught only by hand-audit. This converts "remember
# to scope" into a gate. The check is deliberately blunt: if a SQL string runs
# INSERT/SELECT/UPDATE/DELETE/JOIN against a tenant table and the string has no
# 'channel_id' anywhere, it fails.
#
# Escape hatches for genuine exceptions:
#   * trailing  # tenant-ok        on the statement -> skip that one query
#     (admin cross-channel aggregate, lookup by a globally-unique id, etc.)
#   * anywhere  # tenant-lint: skip-file            -> skip the whole file
#     (known debt parked behind a tracked task)
# ---------------------------------------------------------------------------
_DML_KW = re.compile(r"\b(?:into|from|update|join)\s+([a-z_][a-z0-9_]*)\b")
_DDL_MARKERS = ("create table", "alter table", "drop table",
                "create index", "create trigger", "create unique")


def _m1_tenant_tables() -> set:
    """Tables M1 scoped by channel_id: the ADD_COLUMN list + every RECREATE
    table (these got channel_id via runtime ALTER/recreate, so a CREATE-scan
    alone would miss them). Parsed from m1_multitenant.py via ast (no import)."""
    out: set = set()
    m1 = EXT / "backend" / "migrations" / "m1_multitenant.py"
    if not m1.exists():
        return out
    try:
        tree = ast.parse(m1.read_text(encoding="utf-8"))
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        name = getattr(node.targets[0], "id", "")
        if name == "ADD_COLUMN_TABLES" and isinstance(node.value, ast.List):
            for el in node.value.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    out.add(el.value.lower())
        elif name == "RECREATE_TABLES" and isinstance(node.value, ast.List):
            for el in node.value.elts:
                if isinstance(el, ast.Dict):
                    for k, v in zip(el.keys, el.values):
                        if (isinstance(k, ast.Constant) and k.value == "table"
                                and isinstance(v, ast.Constant)):
                            out.add(str(v.value).lower())
    return out


def _discover_tenant_tables(backend: pathlib.Path) -> set:
    """All channel_id-scoped tables = M1's set UNION any literal CREATE TABLE
    whose body declares a channel_id column (auto-picks up new native tables
    like module_actions / tts_messages / cases without a hardcoded list)."""
    tables = _m1_tenant_tables()
    create_rx = re.compile(
        r"create\s+table\s+(?:if\s+not\s+exists\s+)?[\"'`]?([a-z_][a-z0-9_]*)[\"'`]?\s*\((.*?)\)",
        re.I | re.S,
    )
    for py in backend.rglob("*.py"):
        try:
            txt = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in create_rx.finditer(txt):
            if "channel_id" in m.group(2).lower():
                tables.add(m.group(1).lower())
    return tables


def _sql_strings(tree: ast.AST):
    """Yield (lineno, end_lineno, text) for str literals and f-strings. Python
    pre-joins adjacent string literals into ONE Constant, so the common
    multi-line SQL (implicit concatenation) arrives already whole."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, getattr(node, "end_lineno", None) or node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                elif isinstance(v, ast.FormattedValue):
                    try:
                        parts.append(ast.unparse(v.value))
                    except Exception:
                        parts.append(" ")
            yield node.lineno, getattr(node, "end_lineno", None) or node.lineno, "".join(parts)


def _tenant_violation(text: str, tenant: set):
    """Return the offending tenant table if `text` is an UNSCOPED DML statement on
    a channel_id-scoped table, else None. Pure -> unit-tested by _selftest_tenant.

    A query scoped by channel_id, or by a globally-unique id/FK (id=?, pawn_id,
    guild_id ...) reached through a channel-scoped parent, is OK. The blatant class
    fails: filtered by a NON-id key (username, code) or not filtered at all.
    Limitation: does NOT catch id-GUESSING cross-channel writes -- scope those by hand."""
    low = re.sub(r"\s+", " ", text).strip().lower()
    if not re.match(r"(?:select|insert|update|delete|replace)\b", low):
        return None                       # prose / comment that merely mentions a table
    if "channel_id" in low:
        return None                       # already scoped
    if any(d in low for d in _DDL_MARKERS):
        return None                       # schema DDL, not a tenant query
    if re.search(r"\bset$", low):
        return None                       # "UPDATE t SET " + cols -> WHERE concatenated later
    hit = next((m.group(1) for m in _DML_KW.finditer(low) if m.group(1) in tenant), None)
    if not hit:
        return None                       # touches no tenant table
    if " where " in low:
        scope = low.split(" where ", 1)[1]
    elif "insert into" in low:
        _mm = re.search(r"insert into \w+\s*\(([^)]*)\)", low)
        scope = _mm.group(1) if _mm else low
    else:
        scope = ""                        # SELECT/DELETE with no WHERE -> full-table -> leak
    if re.search(r"\b\w*_id\b|\bid\s*=|\bid\s+in\b|\browid\b", scope):
        return None                       # scoped by a globally-unique id / FK
    return hit


def _selftest_tenant() -> bool:
    """A broken gate that silently passes everything is worse than no gate, so
    verify the matching logic still behaves before trusting a clean run."""
    t = {"viewers"}
    cases = [
        ("SELECT username FROM viewers WHERE username = ?", "viewers"),  # non-id filter -> leak
        ("DELETE FROM viewers", "viewers"),                              # unfiltered -> leak
        ("SELECT u FROM viewers WHERE channel_id = ? AND username = ?", None),  # scoped
        ("SELECT s FROM viewers WHERE pawn_id = ?", None),              # id/FK scoped
        ("SELECT x FROM items WHERE id = ?", None),                     # non-tenant table
        ("UPDATE viewers SET ", None),                                  # mid-concat fragment
        ("the value comes from viewers eventually", None),             # prose, no verb start
    ]
    return all(_tenant_violation(s, t) == ex for s, ex in cases)


def check_tenant_scoping():
    backend = EXT / "backend"
    if not backend.is_dir():
        return
    if not _selftest_tenant():
        errors.append("tenant-scope: linter SELF-TEST FAILED -- gate logic in "
                      "lint_consistency.py is broken (a silent pass hides leaks); fix it")
        return
    tenant = _discover_tenant_tables(backend)
    if not tenant:
        return
    skip_parts = {"migrations", "tests", "__pycache__"}
    for py in sorted(backend.rglob("*.py")):
        if skip_parts & set(py.parts):
            continue
        try:
            src = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "tenant-lint: skip-file" in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.splitlines()
        for lineno, end, text in _sql_strings(tree):
            hit = _tenant_violation(text, tenant)
            if not hit:
                continue
            seg = "\n".join(lines[lineno - 1:end])
            # Suppression: '# tenant-ok' (Python) or '-- tenant-ok' (inside SQL)
            # anywhere in the statement's lines.
            if "tenant-ok" in seg:
                continue
            rel = py.relative_to(EXT).as_posix()
            snippet = re.sub(r"\s+", " ", text).strip()[:90]
            errors.append(
                f"tenant-scope: {rel}:{lineno} query on '{hit}' has no channel_id -> {snippet}"
            )


def main() -> int:
    if EXT is None:
        print("[lint] FAIL: could not locate extension dir (with backend/)")
        return 1
    for fn in (check_version_sync, check_migrations_wired,
               check_manifest_actions, check_currency_glyph,
               check_tenant_scoping):
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

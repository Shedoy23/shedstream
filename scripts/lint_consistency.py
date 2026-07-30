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


def check_manifest_events():
    """Mod pushes an event type that manifest.yaml does not declare -> the
    backend drops it BEFORE the adapter runs (event_not_in_manifest), so the
    mod logs a successful push and nothing happens in the DB.

    This exact class bit twice by hand (hero.properties_snapshot -> the mirror
    was dead; hero.restore_profile -> per-save class never restored). It is the
    dangerous direction and was NOT covered: check_manifest_actions only warns
    about the harmless opposite (declared but unused). HARD error.

    Only literal `PostEventAsync("bannerlord", "some.event"` call sites are
    checkable; pushes built from a variable are invisible here and stay on the
    human.
    """
    man = EXT / "backend" / "modules" / "bannerlord" / "manifest.yaml"
    mod = ROOT / "BannerlordLink" / "src"
    if not man.exists() or not mod.is_dir():
        return
    declared = set(_manifest_event_names(man.read_text(encoding="utf-8")))
    if not declared:
        return
    pushed: dict[str, str] = {}
    pat = re.compile(r'PostEventAsync\(\s*"bannerlord"\s*,\s*"([^"]+)"')
    for cs in mod.rglob("*.cs"):
        try:
            text = cs.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in pat.finditer(text):
            pushed.setdefault(m.group(1), cs.relative_to(ROOT).as_posix())
    missing = sorted(e for e in pushed if e not in declared)
    if missing:
        errors.append(
            "mod pushes event(s) NOT declared in manifest.yaml events: -- the "
            "backend will silently drop them (event_not_in_manifest): "
            + ", ".join("%s (%s)" % (e, pushed[e]) for e in missing)
        )


def _manifest_event_names(text: str) -> list[str]:
    """Same walker as _manifest_action_names, but collecting `events:` blocks
    (top-level + nested under extensions:)."""
    names, mode, mode_indent = [], None, -1
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        item = re.match(r"-\s+(\S+)", s)
        if item:
            if mode == "events":
                names.append(item.group(1))
            continue
        key = re.match(r"(\w+):", s)
        if key:
            if key.group(1) in ("actions", "events"):
                mode, mode_indent = key.group(1), indent
            elif indent <= mode_indent:
                mode = None
    return names


def check_dashboard_mod_config():
    """Готовый config.json на дашборде должен совпадать с тем, что читает мод.

    Дашборд собирает файл настроек за стримера, чтобы тот не правил JSON руками
    (забытая запятая и кавычка-ёлочка из мессенджера — это вечер переписки).
    Но список полей теперь живёт в ДВУХ местах: `BackendConfig.cs` у мода и
    шаблон дашборда. Добавят настройку в мод — дашборд молча продолжит отдавать
    старый файл, стример поставит его и получит поведение по умолчанию, не
    понимая почему.

    Это ровно тот класс «одна правда, две копии», который мы весь день чинили,
    поэтому сразу под машинную проверку. HARD error.
    """
    cs = ROOT / "BannerlordLink" / "src" / "Net" / "BackendConfig.cs"
    tpl = EXT / "backend" / "templates" / "streamer_dashboard.html"
    if not cs.exists() or not tpl.exists():
        return

    fields = set(re.findall(r"public\s+\w+\s+(\w+)\s*\{\s*get;\s*set;",
                            cs.read_text(encoding="utf-8")))
    if not fields:
        return

    m = re.search(r"box\.value = JSON\.stringify\(\{(.*?)\}, null, 2\)",
                  tpl.read_text(encoding="utf-8"), re.S)
    if not m:
        warns.append("dashboard: не нашёл сборку config.json — проверка полей "
                     "мода пропущена")
        return
    ours = set(re.findall(r"(\w+)\s*:", m.group(1)))

    missing = sorted(fields - ours)
    if missing:
        errors.append(
            "dashboard config.json НЕ содержит поля, которые читает мод "
            "(BackendConfig.cs): " + ", ".join(missing) +
            " -- стример получит настройки по умолчанию и не поймёт почему")
    extra = sorted(ours - fields)
    if extra:
        warns.append("dashboard config.json отдаёт поля, которых нет в моде: "
                     + ", ".join(extra))


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


def check_frontend_global_collisions():
    """Two frontend scripts must not declare the same top-level name.

    The 7k-line viewer.js was split into pets.js / shop.js / duels.js / ... but
    they are plain <script> tags, so every top-level `function` and `var` lands
    in ONE shared global scope. Two files declaring the same name is legal
    JavaScript: the one loaded last silently replaces the other. No error, no
    warning -- the code runs, it just runs the wrong function.

    Cost us an hour on 2026-07-22: pets.js and shop.js both declared
    `async function _buyItem`. pets.js is included later (extension.html:469 vs
    461), so every RimWorld shop purchase called the PETS version, POSTed to
    /api/pet/purchase with a URL as item_id, and got back "item not found in
    catalog" -- while the catalog was perfectly fine. 33 such requests in the
    nginx log, none to the RimWorld endpoint. Reading either file alone shows
    nothing wrong, which is why a linter is the right tool here.

    Only files loaded by the SAME shell are compared -- scripts that never share
    a page cannot collide.

    `const`/`let` are skipped on purpose: redeclaring those across scripts is a
    loud SyntaxError, so they cannot cause this silent class of bug.
    """
    frontend = EXT / "frontend"
    if not frontend.is_dir():
        return

    decl_rx = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M)
    var_rx = re.compile(r"^var\s+([A-Za-z_$][\w$]*)\s*=", re.M)

    for shell in ("extension.html", "mobile.html"):
        shell_path = frontend / shell
        if not shell_path.is_file():
            continue
        html = shell_path.read_text(encoding="utf-8", errors="ignore")
        scripts = re.findall(r'<script\s+src="([^"?]+\.js)', html)

        owners: dict[str, list[str]] = {}
        for js in scripts:
            f = frontend / js
            if not f.is_file():
                continue
            src = f.read_text(encoding="utf-8", errors="ignore")
            for name in set(decl_rx.findall(src)) | set(var_rx.findall(src)):
                owners.setdefault(name, []).append(js)

        for name, files in sorted(owners.items()):
            if len(files) > 1:
                # Last one in load order wins -- name the loser explicitly.
                order = [j for j in scripts if j in files]
                errors.append(
                    f"global-collision [{shell}]: '{name}' declared in "
                    f"{', '.join(order)} -- these share one global scope, so "
                    f"{order[-1]} silently overwrites {order[0]}; rename one")


def _bannerlord_campaign_dll():
    """Path to TaleWorlds.CampaignSystem.dll, or None if the game isn't here.

    The game path lives in exactly one place already (the mod's csproj), so we
    read it from there instead of hardcoding it a second time.
    """
    csproj = ROOT / "BannerlordLink" / "src" / "BannerlordLink.csproj"
    if not csproj.is_file():
        return None
    m = re.search(r"<BannerlordPath>(.*?)</BannerlordPath>",
                  csproj.read_text(encoding="utf-8", errors="ignore"))
    if not m:
        return None
    base = m.group(1).replace("&amp;", "&").strip()
    dll = pathlib.Path(base) / "bin" / "Win64_Shipping_Client" / "TaleWorlds.CampaignSystem.dll"
    return dll if dll.is_file() else None


def check_bannerlord_policies():
    """Kingdom-law ids hardcoded in the frontend must exist in the game.

    The law catalog is a hand-written array in viewer-bannerlord.js; the game
    never sends it. So a Bannerlord patch that renames a PolicyObject turns the
    button into a silent no-op: the mod answers policy_not_found, the viewer is
    refunded, but from their side an expensive action (1500 crustics) just
    "does not work". That is exactly how bug report #23 read from the outside.

    The authoritative list lives in code, not XML, so we scan the assembly's
    UTF-16 string literals -- verified 2026-07-22 to return byte-for-byte the
    same 32 ids as decompiling DefaultPolicies, with no extra tooling.

    Degrades quietly: no game installed (CI) -> skip. This check is meant to
    bite on the dev machine, where the pre-commit hook runs.
    """
    front = EXT / "frontend" / "viewer-bannerlord.js"
    if not front.is_file():
        return
    ids = sorted(set(re.findall(
        r"id:\s*'(policy_[a-z_]+)'",
        front.read_text(encoding="utf-8", errors="ignore"))))
    if not ids:
        return

    dll = _bannerlord_campaign_dll()
    if dll is None:
        return  # game not on this machine (CI) -- nothing to compare against

    try:
        blob = dll.read_bytes().decode("utf-16-le", errors="ignore")
    except OSError:
        return
    game = set(re.findall(r"policy_[a-z_]{3,40}", blob))
    if len(game) < 10:
        # Scan clearly did not work (packed/obfuscated build?) -- a silent pass
        # is safer than failing every commit on a bad heuristic.
        warns.append("policy-catalog: could not read policy ids from the game "
                     "assembly -- check skipped, not a frontend problem")
        return

    for pid in ids:
        if pid not in game:
            errors.append(
                f"policy-catalog: '{pid}' is offered in viewer-bannerlord.js but "
                f"does NOT exist in the game -- the button would charge the viewer "
                f"and silently do nothing (mod: policy_not_found)")

    unused = len(game) - len(ids)
    if unused > 0:
        warns.append(
            f"policy-catalog: the game has {len(game)} laws, the extension offers "
            f"{len(ids)} -- {unused} are unreachable for viewers (see DEFERRED.md: "
            f"serve the catalog from the game instead of hardcoding it)")


def check_undefined_names():
    """A name that is used but never bound = guaranteed NameError on that line.

    Why this exists (2026-07-27): migration M97 (c3e3599) added a `channel_id`
    parameter to `_get_last_heal_ts` but left one call site passing a
    `channel_id` that does not exist in that scope. `compileall` is happy --
    the syntax is valid -- so nothing caught it, and the bug sat in the
    ready-to-deploy batch. The endpoint would have returned 500 on the first
    request after deploy, and the frontend calls it on every panel open.
    An external audit found it by reading; this check finds it in a second.

    HARD failure: an undefined name is never intentional in this codebase.
    Soft-skips when pyflakes is absent so a missing dev dependency cannot
    block the owner's commits.
    """
    try:
        from pyflakes.api import checkPath
        from pyflakes.reporter import Reporter
    except ImportError:
        warns.append("undefined-names: pyflakes not installed "
                     "(pip install pyflakes) -- check skipped")
        return

    import io
    backend = EXT / "backend"
    if not backend.is_dir():
        return

    out, err = io.StringIO(), io.StringIO()
    reporter = Reporter(out, err)
    for py in sorted(backend.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        checkPath(str(py), reporter)

    for line in out.getvalue().splitlines():
        if "undefined name" in line:
            # pyflakes prints "<path>:<line>:<col>: message"; the greedy first
            # group is required so a Windows drive letter ("C:\...") is not
            # mistaken for the path/line separator.
            m = re.match(r"^(.*):(\d+):(\d+): (.*)$", line)
            if m:
                try:
                    rel = pathlib.Path(m.group(1)).relative_to(ROOT)
                except ValueError:
                    rel = m.group(1)
                line = f"{rel}:{m.group(2)} -- {m.group(4)}"
            errors.append(f"undefined name -> NameError at runtime: {line}")


def check_sold_actions_have_entry():
    """Every purchasable action must have a way in -- or be tagged service-only.

    Why this exists (2026-07-29). Three cancelled mechanics were found in one
    day still sitting in the price list: hero.tribute_boost (fief rent switched
    off 28.05), hero.smith_item and hero.equip_trophy (BLT-style smithing
    dropped), plus a whole auction router mounted with no UI. Same handwriting
    every time: the mechanic gets switched off where it RUNS and stays on where
    it SELLS. No test catches it -- from a test's point of view nothing broke.

    Rule: an action listed in _PURCHASABLE_ACTIONS must appear as a literal in
    the frontend (i.e. a viewer can reach it), unless its line carries a
    trailing comment marking it service-only.

    Escape hatch: add `# service-only: <why>` on the tuple line.
    """
    bnr = EXT / "backend" / "routes" / "bannerlord.py"
    if not bnr.exists():
        return
    src = bnr.read_text(encoding="utf-8", errors="ignore")
    lines = src.splitlines()

    tree = ast.parse(src)
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") == "_PURCHASABLE_ACTIONS"
                         for t in n.targets)), None)
    if node is None:
        warns.append("sold-actions: _PURCHASABLE_ACTIONS not found -- check skipped")
        return

    frontend = EXT / "frontend"
    parts = []
    for pattern in ("*.js", "*.html"):
        for f in frontend.glob(pattern):
            parts.append(f.read_text(encoding="utf-8", errors="ignore"))
    blob = "\n".join(parts)

    for elt in getattr(node.value, "elts", []):
        if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
            continue
        action = elt.value
        line = lines[elt.lineno - 1] if elt.lineno <= len(lines) else ""
        if "service-only" in line:
            continue
        if action in blob:
            continue
        errors.append(
            f"sold-action without entry point: '{action}' is in "
            f"_PURCHASABLE_ACTIONS (bannerlord.py:{elt.lineno}) but no frontend "
            f"file mentions it -- viewers cannot reach it. Cancelled mechanic "
            f"left on sale? Remove it, or tag the line '# service-only: <why>'."
        )


# ── partial unique index == a LOCK, and a lock needs a keyholder ─────────────
# A partial unique index like
#     CREATE UNIQUE INDEX ... ON t(...) WHERE status = 'pending'
# is not tidiness, it is a lock: while the row sits there, the same request
# cannot be made again. If nobody clears it by age, one lost mod event blocks
# the viewer FOREVER.
#
# This bit twice. Peace offers (fixed June): a stuck row banned that king from
# ever offering peace to that faction again. Policy requests (found 2026-07-30
# in prod DATA, not by reading code): two rows had been pending since 24.07 --
# six days -- because the sweeper existed for peace and was simply forgotten
# for policies.
#
# Rule: a partial unique index whose predicate pins a TRANSIENT status must
# have code that expires such rows by age, or an explicit waiver.
_TRANSIENT_STATUS_RE = re.compile(
    r"""status\s*=\s*['"](pending|queued|requested|offered|waiting|in_progress)['"]""",
    re.I)
# Предикат берём до конца строки или до ';': внутри него ЕСТЬ кавычки
# ('pending'), и первая версия шаблона их исключала — из-за чего группа
# обрывалась и детектор не видел ни одного замка. Поймал собственный селф-тест.
_PARTIAL_UNIQUE_RE = re.compile(
    r"CREATE\s+UNIQUE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s*\((.*?)\)\s*WHERE\s+([^\n;]+)",
    re.I | re.S)
# Waiver: put `partial-lock-ok: <reason>` in a comment near the CREATE INDEX.
_WAIVER_RE = re.compile(r"partial-lock-ok\s*:", re.I)


def _has_age_sweeper(backend, table: str) -> bool:
    """Is there code that expires rows of `table` by AGE?

    Looks for an UPDATE of that table whose statement also carries a
    datetime('now', '-...') threshold. Deliberately loose: the point is to
    catch a table with NO keyholder at all, not to police wording.
    """
    upd = re.compile(r"(?:UPDATE|DELETE\s+FROM)\s+" + re.escape(table) + r"\b", re.I)
    for py in sorted(backend.rglob("*.py")):
        if {"tests", "__pycache__"} & set(py.parts):
            continue
        try:
            src = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in upd.finditer(src):
            window = src[m.start():m.start() + 600]
            # Два законных способа задать порог, оба принимаем:
            #   • сдвиг в запросе      — datetime('now', '-24 hours')
            #   • порог в колонке      — datetime(expires_at) < datetime('now')
            # Первая версия требовала запятую и поэтому не признала сторож
            # предложений брака (он хранит срок в expires_at) — ложное
            # срабатывание. Ложная тревога в линтере дороже пропуска: после неё
            # линтеру перестают верить.
            if re.search(r"datetime\(\s*['\"]now['\"]", window, re.I):
                return True
    return False


def _selftest_partial_index() -> bool:
    """The detector must recognise a synthetic locking index.

    Without this, a regex that silently matches nothing would report a clean
    run and hide exactly the class it was written for.
    """
    sample = ("CREATE UNIQUE INDEX idx_fake_lock ON fake_tbl(channel_id, thing) "
              "WHERE status = 'pending'")
    m = _PARTIAL_UNIQUE_RE.search(sample)
    if not m or m.group(2) != "fake_tbl":
        return False
    if not _TRANSIENT_STATUS_RE.search(m.group(4)):
        return False
    # and it must NOT fire on a non-transient predicate
    other = ("CREATE UNIQUE INDEX idx_alive ON guilds(channel_id, name) "
             "WHERE disbanded_at IS NULL")
    m2 = _PARTIAL_UNIQUE_RE.search(other)
    return bool(m2) and not _TRANSIENT_STATUS_RE.search(m2.group(4))


def check_partial_index_has_sweeper():
    backend = EXT / "backend"
    if not backend.is_dir():
        return
    if not _selftest_partial_index():
        errors.append(
            "partial-lock: linter SELF-TEST FAILED -- the detector no longer "
            "recognises a locking index, so a clean run means nothing; fix "
            "lint_consistency.py")
        return

    sql_sources = []
    mig = backend / "migrations"
    if mig.is_dir():
        sql_sources += sorted(mig.rglob("*.py"))
    dbpy = backend / "database.py"
    if dbpy.is_file():
        sql_sources.append(dbpy)

    seen: dict[str, str] = {}      # index name -> table
    for path in sql_sources:
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in _PARTIAL_UNIQUE_RE.finditer(src):
            idx_name, table, _cols, predicate = m.group(1), m.group(2), m.group(3), m.group(4)
            if not _TRANSIENT_STATUS_RE.search(predicate):
                continue          # not a transient lock (e.g. WHERE deleted_at IS NULL)
            # waiver in the surrounding lines?
            around = src[max(0, m.start() - 400):m.start()]
            if _WAIVER_RE.search(around):
                continue
            seen[idx_name] = table

    for idx_name, table in sorted(seen.items()):
        if not _has_age_sweeper(backend, table):
            errors.append(
                f"partial-lock: index '{idx_name}' locks {table} while a row "
                f"stays in a transient status, but nothing expires those rows "
                f"by age. One lost mod event blocks the viewer forever (this "
                f"already happened twice: peace offers, policy requests). Add a "
                f"sweeper -- an UPDATE {table} ... WHERE <ts> < datetime('now', "
                f"'-N hours') called from a background loop in main.py -- or "
                f"waive it with a `partial-lock-ok: <reason>` comment next to "
                f"the CREATE INDEX")


_SEASON_PICK_RE = re.compile(
    r"FROM\s+duel_seasons[^\"']*?finished\s*=\s*0[^\"']*?(?:\"\s*\n\s*\")?[^\"']*?LIMIT\s+1",
    re.IGNORECASE | re.DOTALL)

# Исторический баг дословно — на нём проверяем, что детектор жив.
_SEASON_SELFTEST = (
    '"SELECT id, ends_at FROM duel_seasons "\n'
    '"WHERE channel_id = ? AND game_type = ? AND finished = 0 "\n'
    '"ORDER BY id DESC LIMIT 1",\n')


def _selftest_season_pick() -> bool:
    """Детектор обязан узнавать исторический баг, иначе чистый прогон пуст."""
    return bool(_SEASON_PICK_RE.search(_SEASON_SELFTEST.replace('"\n"', "")))


def _func_source(src: str, func_name: str):
    """Исходник функции `func_name` (по AST). None — если её нет."""
    import ast as _ast
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return None
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.AsyncFunctionDef, _ast.FunctionDef)) \
                and node.name == func_name:
            return _ast.get_source_segment(src, node)
    return None


def check_season_rotation_sweeps_all():
    """Ротация сезона обязана разбирать ВСЕ незакрытые сезоны, а не свежий.

    Класс (найден 29.07 в дуэлях, 30.07 — в костях и крестиках): выборка
    `... finished = 0 ORDER BY id DESC LIMIT 1` видит только последний
    незакрытый сезон. Висящий рядом старый не закрывается НИКОГДА — ни призов,
    ни закрытия. На проде так накопились три сезона rps и один tictactoe.

    Файлы трёх мини-игр — близнецы, и фикс дважды оставался в одном из них.
    Эта проверка и существует затем, чтобы третьего раза не было.
    """
    backend = EXT / "backend" / "routes"
    if not backend.is_dir():
        return
    if not _selftest_season_pick():
        errors.append(
            "season-rotation: linter SELF-TEST FAILED -- детектор перестал "
            "узнавать исторический баг, значит чистый прогон ничего не значит; "
            "чинить lint_consistency.py")
        return

    for name in ("duel.py", "dice.py", "tictactoe.py"):
        path = backend / name
        if not path.is_file():
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Смотрим ТОЛЬКО тело ротации. `finished = 0 ... LIMIT 1` законно там,
        # где читают «какой сезон идёт сейчас» — ошибка только в разборе.
        body = _func_source(src, "check_season_end")
        if body is None:
            continue
        # Склеиваем соседние строковые литералы: SQL разбит по строкам.
        flat = re.sub(r'"\s*\n\s*"', "", body)
        if _SEASON_PICK_RE.search(flat):
            errors.append(
                f"season-rotation: routes/{name} выбирает незакрытый сезон с "
                f"LIMIT 1 -- висящий рядом просроченный сезон не закроется "
                f"никогда (ни призов, ни закрытия). Брать ВСЕ строки с "
                f"finished = 0 и разбирать каждую, как в routes/duel.py")


_CREDIT_RE = re.compile(
    r"(add_points_tx\s*\(|add_points\s*\(|points\s*=\s*points\s*\+)", re.IGNORECASE)
# Возврат уплаченного — разрешён правилом явно. Узнаём по имени функции.
_REFUND_FN_RE = re.compile(r"refund|_on_action_failed|expire", re.IGNORECASE)
_CURRENCY_WAIVER = "currency-ok:"


def _selftest_currency_boundary() -> bool:
    """Детектор обязан узнавать начисление в игровом модуле."""
    bad = 'await db.add_points(username, 500, channel_id=cid)'
    good = 'await db.remove_points_tx(conn, username, 500, cid)'
    return bool(_CREDIT_RE.search(bad)) and not _CREDIT_RE.search(good)


def check_currency_boundary():
    """Крустики начисляются ТОЛЬКО в ядре; в игровых модулях — лишь возврат.

    Решение владельца 2026-07-29 (`PLATFORM_VISION.md` §«Граница валют»):
    крустики зарабатываются просмотром и активностью, а внутри интеграций
    только ТРАТЯТСЯ. Причина историческая: рента с феодов уже вырезана в мае за
    то, что зритель богател, ничего не делая. Возврат уплаченного — не
    нарушение.

    До 2026-07-31 у правила не было машинной проверки: оно жило в CLAUDE.md и
    держалось на внимательности. Эта проверка сразу нашла живой пример —
    отключённый аукцион (`routes/bannerlord_auctions.py`), который двигает
    крустики между зрителями и вернулся бы к жизни от одной строки
    `include_router`.

    Исключения помечаются `# currency-ok: <причина>` на строке начисления.
    """
    backend = EXT / "backend"
    if not backend.is_dir():
        return
    if not _selftest_currency_boundary():
        errors.append(
            "currency-boundary: linter SELF-TEST FAILED -- детектор не узнаёт "
            "начисление, значит чистый прогон ничего не значит")
        return

    targets = []
    mod_dir = backend / "modules"
    if mod_dir.is_dir():
        targets += [p for p in sorted(mod_dir.rglob("*.py"))
                    if p.parent.name not in ("modules",)]
    routes = backend / "routes"
    if routes.is_dir():
        for game in ("bannerlord", "rimworld", "shedcolony"):
            targets += sorted(routes.glob(f"{game}*.py"))
    rw = backend / "rimworld.py"
    if rw.is_file():
        targets.append(rw)

    for path in targets:
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        # Карта «строка → имя ближайшей функции», чтобы отличить возврат.
        owner = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                end = getattr(node, "end_lineno", node.lineno)
                for ln in range(node.lineno, end + 1):
                    owner[ln] = node.name
        src_lines = src.splitlines()
        for i, line in enumerate(src_lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if not _CREDIT_RE.search(line):
                continue
            # Оговорка ищется на самой строке и в трёх строках над ней: SQL
            # часто разбит по строкам, и коммент естественно ставить перед ним.
            window = src_lines[max(0, i - 4):i]
            if _CURRENCY_WAIVER in line or any(_CURRENCY_WAIVER in w for w in window):
                continue
            fn = owner.get(i, "")
            if _REFUND_FN_RE.search(fn):
                continue          # возврат уплаченного — разрешён
            rel = path.relative_to(EXT / "backend")
            errors.append(
                f"currency-boundary: {rel}:{i} начисляет крустики внутри "
                f"игрового модуля (функция `{fn or '?'}`). Крустики зарабатываются "
                f"только в ядре; здесь допустим лишь возврат уплаченного. "
                f"Если это всё-таки возврат — назови функцию так, чтобы это было "
                f"видно, либо поставь `# {_CURRENCY_WAIVER} <причина>`")


def main() -> int:
    if EXT is None:
        print("[lint] FAIL: could not locate extension dir (with backend/)")
        return 1
    for fn in (check_version_sync, check_migrations_wired,
               check_manifest_actions, check_manifest_events,
               check_dashboard_mod_config, check_currency_glyph,
               check_tenant_scoping, check_bannerlord_policies,
               check_frontend_global_collisions, check_undefined_names,
               check_sold_actions_have_entry,
               check_partial_index_has_sweeper,
               check_season_rotation_sweeps_all,
               check_currency_boundary):
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

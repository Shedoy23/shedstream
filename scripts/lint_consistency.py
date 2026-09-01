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


def check_declared_gold_is_charged():
    """Бэкенд объявил цену в динарах — мод обязан её списать.

    Класс найден внешним аудитом 31.07 и ПОДТВЕРЖДЁН прогоном в игре: бэкенд
    для `hero.set_gender` / `hero.marry` / `hero.make_baby` проверял баланс и
    клал в задание `hero_gold_cost` (50 000 / 50 000 / 100 000), а мод это поле
    не читал ВООБЩЕ — ни один обработчик. Действия выполнялись бесплатно.

    Прятал дыру комментарий в `SetGenderHandler`: «backend gold-check уже
    выполнен, здесь только применение». Звучит как объяснение — а бэкенд лишь
    проверял, но не списывал.

    Проверяем связку: для каждого действия, которому бэкенд объявляет цену в
    динарах, C#-обработчик того же типа обязан звать `HeroGoldCharge.TryCharge`
    (или списывать `GiveGoldAction` сам — так делает `EquipItemHandler`).
    """
    backend = EXT / "backend" / "routes" / "bannerlord.py"
    mod = ROOT / "BannerlordLink" / "src" / "Actions"
    if not backend.is_file() or not mod.is_dir():
        return

    src = backend.read_text(encoding="utf-8", errors="ignore")
    # Действия, у которых в их ветке `_prepare_action` появляется hero_gold_cost.
    priced: dict[str, int] = {}
    current = None
    for i, line in enumerate(src.splitlines(), 1):
        m = re.search(r'action_type\s*==\s*"([\w.]+)"', line)
        if m:
            current = m.group(1)
        if 'data["hero_gold_cost"]' in line and "= 0" not in line and current:
            priced.setdefault(current, i)
    if not priced:
        warns.append("gold-charge: не нашёл ни одного объявления hero_gold_cost "
                     "— проверка молчит, посмотри, не переехало ли поле")
        return

    handlers: dict[str, str] = {}
    for cs in sorted(mod.rglob("*.cs")):
        try:
            text = cs.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in re.finditer(r'ActionType\s*=>\s*"([\w.]+)"', text):
            handlers[m.group(1)] = text

    for action, line_no in sorted(priced.items()):
        text = handlers.get(action)
        if text is None:
            continue          # backend-only действие, мод его не исполняет
        if "HeroGoldCharge.TryCharge" in text or "GiveGoldAction" in text:
            continue
        errors.append(
            f"gold-charge: бэкенд объявляет цену в динарах для `{action}` "
            f"(routes/bannerlord.py:{line_no}), а его C#-обработчик её НЕ "
            f"списывает — действие выполняется бесплатно. Позови "
            f"`HeroGoldCharge.TryCharge(hero, data, actionId, \"{action}\")` "
            f"перед применением эффекта")


# Цены, вписанные во фронт числом, — известный долг. Пока фронт заморожен под
# ревью, чинить их нельзя, поэтому известные места перечислены здесь и дают
# предупреждение, а всякое НОВОЕ место — ошибку. Убрав последнее, удалить и
# список, и эту ветку: проверка станет просто жёсткой.
# Список ПУСТ с 2026-08-20: обе цены исправлены, и поблажка снята вместе с ними.
# Пока он был непустым, линтер молчал ровно про тот дефект, ради которого его и
# писали, — это цена, которую платит послабление за «известный долг». Новую
# запись сюда добавлять только вместе с датой и условием снятия, иначе она
# останется навсегда.
FROZEN_PRICE_LITERALS: set = set()


def check_frontend_price_literals():
    """Цена крустиками, вписанная во фронт числом, разъедется с бэкендом.

    Класс всплыл дважды. Июль: `recruit_vassal_clan` (3M динаров) держал цену
    числом в кнопке и попал в changelog как переведённый на бэкенд. Август:
    кнопки мастерской и каравана показывали `1000`/`1500` крустиков, тогда как
    бэкенд с 2026-05-29 берёт `2500`/`4000` и объявленные на кнопке динары не
    берёт вовсе. Три месяца обе стороны по отдельности выглядели правильными.

    Ловит ровно правило проекта: с бэкенда — числа, во фронте — только показ.
    Поэтому проверяется не совпадение с сервером (фронт может считать цену как
    угодно), а сам факт числового литерала в цене: его там быть не должно.
    """
    fe = EXT / "frontend"
    if not fe.is_dir():
        return
    call = re.compile(r"_bnrPrice(?:Html)?\(\s*([\w.]+)\s*,\s*([\w.]+)\s*\)")
    for path in sorted(fe.glob("viewer*.js")):
        for line_no, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            for m in call.finditer(line):
                left, right = m.group(1), m.group(2)
                literals = [a for a in (left, right) if a.isdigit() and int(a)]
                if not literals:
                    continue
                where = f"{path.name}:{line_no}"
                message = (
                    f"price-literal: {where} `_bnrPrice({left}, {right})` "
                    f"hardcodes a price in the frontend -- it must come from "
                    f"the backend, or it drifts silently and the viewer pays "
                    f"something other than the button shows")
                if (path.name, left, right) in FROZEN_PRICE_LITERALS:
                    warns.append(message + " [known debt, frontend frozen for "
                                 "review -- fix lands in 0.0.3]")
                else:
                    errors.append(message)


# Сколько цен, вписанных числом, сейчас во фронте — по файлам. Это НЕ цель, а
# исходная отметка храповика: расти нельзя, уменьшать нужно.
#
# Откуда взялось. 2026-08-20 нашли, что форма покупки мастерской показывала
# 💎1000 при списании 2500, и починили. Заодно посчитали остальное: 90 мест в
# девяти файлах. Разом их не перенести — это девять панелей и три игры, — но и
# оставлять без присмотра нельзя: класс уже кусал трижды (вассальный клан в
# июле, мастерская с караваном в августе, и в extension.html до сих пор висит
# комментарий про «100💎 при реальных 200💎»).
#
# Правило простое: добавил во фронт ещё одну цену числом — линтер падает.
# Перенёс цену на /config — уменьши отметку в этой таблице.
PRICE_LITERAL_BASELINE = {
    "family.js": 1,
    "guilds.js": 2,
    "pawn.js": 7,
    "viewer-bannerlord.js": 21,   # 2026-09-01: -7 вместе с блоком «Случайный товар»
    "viewer-rimworld.js": 4,
    "viewer-shedcolony.js": 28,
    "voting.js": 8,
    "extension.html": 6,
    "mobile.html": 6,
}

_PRICE_TEXT = re.compile(r"(\d[\d\s_]{1,9})\s*(💎|💰|крустик|дина)", re.IGNORECASE)


def check_frontend_price_literal_growth():
    """Храповик: число цен, вписанных во фронт вручную, не должно расти.

    Полный перенос на `/config` — работа на несколько заходов, и пока она идёт,
    единственное, что нельзя допустить, — чтобы свалка пополнялась. Проверка
    считает по файлам и падает на любом приросте.

    Почему не «запретить совсем»: тогда линтер был бы красным с первого дня и
    его бы отключили. Храповик даёт двигаться в одну сторону.
    """
    frontend = EXT / "frontend"
    if not frontend.is_dir():
        return
    for name, allowed in sorted(PRICE_LITERAL_BASELINE.items()):
        path = frontend / name
        if not path.is_file():
            continue
        count = 0
        for line in path.read_text(encoding="utf-8", errors="ignore").split("\n"):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            for m in _PRICE_TEXT.finditer(line):
                digits = m.group(1).replace(" ", "").replace("_", "")
                if digits.isdigit() and int(digits) >= 50:
                    count += 1
        if count > allowed:
            errors.append(
                f"price-literal-growth: {name} — цен, вписанных числом, стало "
                f"{count} вместо {allowed}. Новую цену брать из /config, а не "
                f"вписывать: числа во фронте расходятся с бэкендом молча, "
                f"и это уже трижды доходило до зрителя")
        elif count < allowed:
            warns.append(
                f"price-literal-baseline: {name} — теперь {count} вместо "
                f"{allowed}, отметку в PRICE_LITERAL_BASELINE пора опустить, "
                f"иначе храповик перестанет держать достигнутое")



def check_chat_channel_scoping():
    """Функция знает channel_id — обязана передать его при отправке в чат.

    Почему это важнее, чем выглядит. Если канал не указан, BotCore берёт его из
    ContextVar запроса, а когда контекста нет (фоновая задача, стартовый job) —
    из «канала по умолчанию», то есть ПЕРВОГО в реестре. С одним стримером это
    невидимо. Со вторым его объявление уходит в чужой чат, а свой молчит.

    Ровно так и было найдено 2026-08-22: `routes/duel.py:check_season_end`
    закрывал сезон из стартовой задачи и слал «сезон завершён» без канала,
    хотя соседние мини-игры (dice, tictactoe) канал передают. Проверка ловит
    именно этот признак — «функция знает канал, но не воспользовалась им».
    """
    import ast

    backend = EXT / "backend"
    offenders = []
    for path in backend.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if "/tests/" in rel or "/migrations/" in rel:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            if "channel_id" not in params:
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if name not in ("send_message", "send_announcement"):
                    continue
                kw = {k.arg for k in node.keywords}
                if "channel_id" in kw or "channel_login" in kw:
                    continue
                if name == "send_announcement" and node.args:
                    continue          # send_announcement(cid, text) — канал позиционно
                offenders.append(f"{rel}:{node.lineno} внутри {fn.name}()")

    for o in offenders:
        errors.append(
            "chat-scoping: отправка в чат без channel_id, хотя функция его знает "
            f"({o}). Без канала сообщение уйдёт в чат первого стримера в реестре."
        )



def check_auto_messages_neutral():
    """Общие автосообщения не должны содержать ничего про конкретный канал.

    `AUTO_MESSAGES` уходит в чат КАЖДОГО канала реестра. До 2026-08-22 в нём
    жили DonationAlerts, Boosty и Telegram владельца — второму стримеру бот
    рекламировал бы чужие донаты в его собственном чате. Это тот же класс, что
    захардкоженные цены во фронте: данные одного арендатора в общем месте.

    Признак, который ловим: ссылка в общем сообщении. Личное живёт в таблице
    `channel_auto_messages` (m114) и подмешивается per-channel.
    """
    import ast

    cfg = EXT / "backend" / "config.py"
    tree = ast.parse(cfg.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "AUTO_MESSAGES" not in names:
            continue
        if not isinstance(node.value, ast.List):
            continue
        for item in node.value.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                continue
            text = item.value
            marker = next(
                (m for m in ("http://", "https://", "t.me/", "www.") if m in text),
                None,
            )
            if marker:
                errors.append(
                    "auto-messages: общее автосообщение содержит ссылку "
                    f"({marker!r}, строка {item.lineno}). Оно уйдёт в чат КАЖДОГО "
                    "стримера — личные ссылки держать в channel_auto_messages."
                )



def check_migrations_self_register():
    """Миграция обязана записать себя в migrations_applied и закоммитить.

    Ledger ведут сами миграции (конвенция всех m1..m113), а не вызывающий код.
    Миграция, которая этого не делает, во-первых прогоняется заново на каждом
    старте, во-вторых — и это хуже — её собственные INSERT'ы остаются
    незакоммиченными, потому что коммит идёт той же строкой. Ровно так
    2026-08-22 m114 создала таблицу, но не перенесла в неё ни одного
    сообщения: выглядело как успешный деплой, а данных не было.
    """
    mig_dir = EXT / "backend" / "migrations"
    if not mig_dir.is_dir():
        return
    for path in sorted(mig_dir.glob("m*_*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "async def apply" not in text:
            continue
        rel = path.relative_to(ROOT).as_posix()
        # Ищем именно ЗАПИСЬ в ledger, а не любое упоминание таблицы: почти
        # каждая миграция начинается с CREATE TABLE IF NOT EXISTS
        # migrations_applied, и проверка на подстроку проходила бы всегда.
        # Первая редакция этого правила так и не поймала свой же баг —
        # обнаружено обязательным прогоном «красным».
        if "INTO migrations_applied" not in text:
            errors.append(
                f"migration-ledger: {rel} не пишет себя в migrations_applied — "
                "будет прогоняться на каждом старте."
            )
        elif "conn.commit()" not in text:
            errors.append(
                f"migration-ledger: {rel} не делает conn.commit() — её записи "
                "не сохранятся (так m114 потеряла сид 2026-08-22)."
            )


def check_rule_links():
    """Ссылка из правила в LESSONS.md обязана находить свой текст.

    24.08 правила в CLAUDE.md сократили, а истории, из которых они выросли,
    вынесли в LESSONS.md. Ссылка «→ LESSONS.md, «имя правила»» — единственное,
    что связывает правило с его причиной; правило без причины через полгода
    читается как догма, и с ним начинают спорить вместо того, чтобы соблюдать.

    Почему это ловим машиной: до сокращения правила ссылались друг на друга по
    НОМЕРАМ (§2c, §5b). Перенумерация ломала ссылки молча — они оставались
    синтаксически валидными и указывали не туда. Проверять ссылки глазами
    оказалось невозможно ровно потому, что сломанная ссылка выглядит как целая.
    """
    lessons = ROOT / "LESSONS.md"
    if not lessons.is_file():
        errors.append(
            "rule-links: нет LESSONS.md — правила в CLAUDE.md ссылаются на "
            "истории, которых больше нет в репозитории."
        )
        return
    text = lessons.read_text(encoding="utf-8", errors="replace")

    targets = [ROOT / "CLAUDE.md"]
    personal = pathlib.Path.home() / ".claude" / "CLAUDE.md"
    if personal.is_file():
        targets.append(personal)

    for path in targets:
        if not path.is_file():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        for name in re.findall(r"`LESSONS\.md`,\s*[«\"']([^»\"']+)[»\"']", src):
            if name.strip() not in text:
                errors.append(
                    f"rule-links: {path.name} ссылается на «{name}» в "
                    "LESSONS.md, а такого текста там нет."
                )
        # Ссылка на правило по НОМЕРУ — та самая мина, которую мы разминировали:
        # номер меняется при любой вставке правила выше по списку.
        for num in re.findall(r"CLAUDE\.md\s*§\s*\d", src):
            errors.append(
                f"rule-links: {path.name} ссылается на правило по номеру "
                f"({num.strip()}) — ссылаться надо по названию."
            )

def check_status_is_a_window():
    """STATUS.md обязан остаться витриной, а не дневником.

    Правило «STATUS.md — 10 строк, что сейчас» стояло в CLAUDE.md с самого
    начала, а сам файл к 24.08 разросся до 448 строк: копились доказанные
    факты, история заморозки фронта, план работ. Разрослась витрина — значит,
    содержимое уехало не в свой файл, и его не найдёт тот, кто пойдёт за ним
    в RUNBOOK или ROADMAP.

    Проверяем не «строк меньше N» (перенос строк — вопрос ширины), а число
    пунктов витрины: их должно быть не больше десяти.
    """
    path = ROOT / "STATUS.md"
    if not path.is_file():
        errors.append("status-window: нет STATUS.md — витрина «что сейчас» пропала.")
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    # Витрина = маркированные пункты до раздела «Правило обновления».
    head = text.split("## Правило обновления")[0]
    bullets = [ln for ln in head.splitlines() if ln.startswith("- ")]
    if len(bullets) > 10:
        errors.append(
            f"status-window: в STATUS.md {len(bullets)} пунктов витрины при "
            "пределе 10 — содержимое уехало не в свой файл (история -> "
            "docs/archive/, операционка -> RUNBOOK.md, план -> ROADMAP.md, "
            "отложенное -> DEFERRED.md)."
        )
    if "Обновлено:" not in head:
        errors.append("status-window: в STATUS.md нет строки «Обновлено:» — "
                      "витрина без даты не отличается от протухшей.")

def check_runbook_health():
    """RUNBOOK: оглавление совпадает с разделами, ссылки резолвятся, дата честная.

    Рунбук — справочник: его метрика не «короче», а «находится за десять
    секунд». К 24.08 в нём было два раздела, которых НЕ БЫЛО в оглавлении, и
    один из них — «что проверять, когда всё сломалось», то есть самый нужный в
    кризис. Плюс шапка месяц утверждала «последняя ревизия 2026-07-29», хотя
    файл правили в августе десяток раз.

    Три проверки:
      1. каждый `## N.` раздел присутствует в оглавлении и наоборот;
      2. ссылки вида `RUNBOOK.md §N «Название»` из других файлов ведут в
         существующий раздел с ТЕМ ЖЕ названием (номер без названия — мина:
         перенумерация ломает его молча);
      3. «Последняя ревизия» не старше даты последнего коммита, тронувшего файл.
    """
    path = ROOT / "RUNBOOK.md"
    if not path.is_file():
        errors.append("runbook: нет RUNBOOK.md — операционная правда пропала.")
        return
    text = path.read_text(encoding="utf-8", errors="replace")

    heads = re.findall(r"^## (\d+)\. (.+)$", text, flags=re.M)
    toc_block = text.split("## Содержание", 1)[-1].split("\n---\n", 1)[0]
    toc = re.findall(r"^(\d+)\. \[(.+?)\]", toc_block, flags=re.M)
    if [(n, t_) for n, t_ in heads] != [(n, t_) for n, t_ in toc]:
        in_heads = {f"{n}. {t_}" for n, t_ in heads}
        in_toc = {f"{n}. {t_}" for n, t_ in toc}
        for miss in sorted(in_heads - in_toc):
            errors.append(f"runbook: раздел «{miss}» есть в файле, но не в оглавлении — "
                          "в кризис его никто не найдёт.")
        for extra in sorted(in_toc - in_heads):
            errors.append(f"runbook: оглавление обещает «{extra}», а такого раздела нет.")

    known = {n: t_ for n, t_ in heads}
    # Обходим ТОЛЬКО файлы под git: rglob спотыкается о битые junction-точки в
    # .claude/ и валит проверку целиком (поймано на первом же прогоне).
    import subprocess
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                            capture_output=True, timeout=30)
    for rel in listed.stdout.decode("utf-8", "replace").splitlines():
        if not rel.endswith((".md", ".py", ".ps1", ".js")):
            continue
        if rel.startswith(("dist/", "docs/archive/")) or rel == "RUNBOOK.md":
            continue
        src = ROOT / rel
        if not src.is_file():
            continue
        body = src.read_text(encoding="utf-8", errors="replace")
        for num, name in re.findall(r"RUNBOOK(?:\.md)?`?\s*§\s*(\d+)\s*«([^»]+)»", body):
            # Достаточно, чтобы ссылка называла НАЧАЛО заголовка: «§6 «Проверки»»
            # для «6. Проверки: как доказать, что работает» — законно, а вот
            # уехавший номер так не пройдёт, ради чего проверка и заводилась.
            actual = known.get(num, "")
            if not actual.lower().startswith(name.strip().lower()):
                errors.append(
                    f"runbook: {rel} ссылается на §{num} «{name}», а там "
                    f"«{actual or 'раздела нет'}»."
                )
        for bare in re.findall(r"RUNBOOK(?:\.md)?`?\s*§\s*\d+\b(?!\s*«)", body):
            errors.append(f"runbook: {rel} — ссылка «{bare.strip()}» без названия "
                          "раздела; перенумерация сломает её молча.")

    # Внутренние ссылки «см. §N» — тот же класс: 24.08 перенумерация оставила
    # в кризисном разделе ссылку «см. §2», которая после перестановки указывала
    # на сам этот раздел. Снаружи проверка их не видела: перед § нет слова
    # RUNBOOK. Поэтому требуем название и здесь.
    for bare in re.findall(r"§\s*\d+\b(?!\s*«)", text):
        errors.append(f"runbook: внутренняя ссылка «{bare.strip()}» без названия "
                      "раздела — перенумерация переставит её молча.")
    for num, name in re.findall(r"§\s*(\d+)\s*«([^»]+)»", text):
        actual = known.get(num, "")
        if not actual.lower().startswith(name.strip().lower()):
            errors.append(f"runbook: внутренняя ссылка §{num} «{name}» ведёт в "
                          f"«{actual or 'раздел, которого нет'}».")

    m = re.search(r"Последняя ревизия:\s*(\d{4}-\d{2}-\d{2})", text)
    if not m:
        errors.append("runbook: нет строки «Последняя ревизия» — нечем отличить "
                      "свежий файл от протухшего.")
        return
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%ad",
                              "--date=short", "--", "RUNBOOK.md"],
                             capture_output=True, timeout=20)
        last = out.stdout.decode().strip()
    except Exception:
        return
    if last and m.group(1) < last:
        errors.append(
            f"runbook: «Последняя ревизия: {m.group(1)}», а файл правили {last} — "
            "строка врёт (так она врала месяц)."
        )

def check_manager_catch_filters():
    """Обработчики Manager ловят сбои через IsExpected, а не списком типов.

    16.08 установка в защищённую папку закрывала приложение молча:
    UnauthorizedAccessException наследуется от SystemException и не подходил
    под фильтр, который перечислял типы руками. Список типов живёт в
    ManagerFailureMessage.IsExpected — фильтр, который его дублирует, молча
    разъезжается с ним. 24.08 нашлось ещё четыре таких фильтра на путях входа
    и подключения (внутри них пишется состояние на диск).

    Пустой список типов в самом IsExpected тоже ошибка: тогда проверка
    проходит, а ловить перестаёт всё.
    """
    app = EXT.parent / "ShedLink.Manager" / "src" / "ShedLink.Manager.App" if EXT else None
    root_app = ROOT / "ShedLink.Manager" / "src" / "ShedLink.Manager.App"
    app = root_app if root_app.is_dir() else app
    if not app or not app.is_dir():
        return
    for path in sorted(app.rglob("*.cs")):
        rel = path.relative_to(ROOT).as_posix()
        if "/bin/" in rel or "/obj/" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        pattern = "catch \(Exception \w+\) when \(([^{]*?)\)"
        for m in re.finditer(pattern, text):
            cond = " ".join(m.group(1).split())
            if "IsExpected" in cond:
                continue
            # Лазейка как у tenant-lint: узкий фильтр бывает намеренным
            # (лог сбоя обязан глотать только ошибки записи; загрузка каталога
            # ловит ещё и JsonException, которого в общем списке нет).
            # Причину писать обязательно — молчаливое исключение вернёт класс.
            head = text[: m.start()].rsplit(chr(10), 3)[0] if m.start() else ""
            near = text[max(0, m.start() - 260): m.start()]
            if "catch-ok:" in near:
                continue
            if " or " in cond and "Exception" in cond:
                line = text[: m.start()].count(chr(10)) + 1
                errors.append(
                    f"manager-catch: {rel}:{line} перечисляет типы исключений "
                    "руками вместо ManagerFailureMessage.IsExpected — так "
                    "16.08 отказ Windows в правах закрыл приложение молча."
                )

def check_mobile_view_age_rating():
    """Мобильная оболочка не несёт механик со случайным исходом.

    24.08 Twitch отклонил 0.0.2 по правилу 3.5: мобильный вид не должен
    превышать возрастной рейтинг магазина (ссылка на Apple §4.7), а игры с
    азартной ОРИЕНТАЦИЕЙ туда не допускаются. Механики у нас без ставок —
    претензия к тому, как поверхность читается, а не к деньгам.

    Убраны кубики и кейсы. Дуэли (RPS) и крестики ОСТАВЛЕНЫ намеренно: в них
    нет системной случайности — `routes/rps.py` объявляет генератор и нигде его
    не использует, а автоход крестиков по таймауту с 01.09 детерминирован. Это
    проверяемо ревьюером, и прятать их значило бы сдать то, что защищать легко.

    Правило держим машиной, потому что расхождение оболочек выглядит как
    недосмотр: `AUDIT_SPEC.md` годом раньше требовал обратного — чтобы состав
    скриптов совпадал. Первая же «уборка ради симметрии» вернёт кубики в
    мобильный вид и уронит следующую подачу.
    """
    if EXT is None:
        return
    shell = EXT / "frontend" / "mobile.html"
    if not shell.is_file():
        return
    text = shell.read_text(encoding="utf-8", errors="replace")
    for name in ("dice.js", "cases.js"):
        if 'src="%s' % name in text:
            errors.append(
                f"mobile-3.5: mobile.html снова грузит {name} — механики со "
                "случайным исходом запрещены в мобильном виде (отказ ревью "
                "24.08, правило 3.5)."
            )
    for marker in ('data-action="dice"', 'data-action="cases"'):
        if marker in text:
            errors.append(
                f"mobile-3.5: mobile.html снова показывает {marker} — эту "
                "карточку убрали по отказу ревью 24.08 (правило 3.5)."
            )


def main() -> int:
    if EXT is None:
        print("[lint] FAIL: could not locate extension dir (with backend/)")
        return 1
    for fn in (check_frontend_price_literal_growth,
               check_version_sync, check_migrations_wired,
               check_manifest_actions, check_manifest_events,
               check_dashboard_mod_config, check_currency_glyph,
               check_tenant_scoping, check_bannerlord_policies,
               check_frontend_global_collisions, check_undefined_names,
               check_sold_actions_have_entry,
               check_partial_index_has_sweeper,
               check_season_rotation_sweeps_all,
               check_currency_boundary,
               check_frontend_price_literals,
               check_declared_gold_is_charged,
               check_chat_channel_scoping,
               check_auto_messages_neutral,
               check_migrations_self_register,
               check_rule_links,
               check_status_is_a_window,
               check_runbook_health,
               check_manager_catch_filters,
               check_mobile_view_age_rating):
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

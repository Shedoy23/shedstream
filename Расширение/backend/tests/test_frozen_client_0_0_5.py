"""
test_frozen_client_0_0_5.py — сервер не ломает замороженного клиента 0.0.5.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_frozen_client_0_0_5.py

ЗАЧЕМ (план frontend freeze 11.09, раздел 2).
    Панель зрителя на CDN Twitch замерзает до следующего ревью, бэкенд
    деплоится за минуты. После заморозки бэкенд продолжит меняться — и каждый
    раз должен оставаться понятным ИМЕННО тому клиенту, что лежит в Twitch.
    Прежние тесты проверяли текущее дерево фронта; единственный гейт
    совместимости держал 0.0.1, чей архив утерян, поэтому он сверял форму
    ответов, прописанную вручную. Для 0.0.5 архив есть — и здесь впервые
    исполняется сам клиент из него.

ЧТО НАСТОЯЩЕЕ, А ЧТО ПОДМЕНЕНО.
    Настоящее: клиент — байт в байт архив из фикстуры (SHA-256 сверяется
    первым делом, не тот архив — проверка не идёт вовсе); порядок скриптов —
    из его же extension.html; ответы — от настоящих обработчиков бэкенда на
    временной базе. Где клиент сам собирает запрос (вход, согласие на цену,
    подтверждение уведомлений, покупка, открытие кейса), стенд идёт в ДВА
    прохода: записывает тело, которое отправил клиент, отдаёт его настоящему
    обработчику и возвращает клиенту его настоящий ответ. Так проверяется
    контракт в обе стороны, а не только разбор ответа.
    Подменено на границе: сеть (fetch отдаёт полученные ответы), DOM
    (записывающие элементы), проверка Twitch JWT в обработчиках, кроме входа
    (там JWT подписывается настоящим ключом), и отметка «игра на связи».
    Интерпретацию ответов клиентом не подменяет ничто.

ПОКРЫТО (семья → варианты):
    вход и состояние → настоящий вход, баланс, ноль, «не опознан», нет
                       необязательных полей, лишнее поле, обрыв сети;
    цены ядра        → изменённая цена, допустимый ноль, нет поля, лишнее
                       поле, отказ API;
    каталог и цена   → цена с сервера, изменённая прогрессивная цена, лишние
                       и отсутствующие поля, согласие на цену в два прохода
                       («Цена изменилась»), успешная покупка, «игра не запущена»;
    кейсы и уведомления → список, открытие в два прохода, отказ, сбой списка,
                       уведомления с возвратом и без, подтверждение показа;
    платные действия → успех в два прохода, отказ сервера, обрыв сети и
                       повтор после него (замок двойного клика отпущен).
    Отрицательный контроль: заведомо несовместимые ответы (баланс под другим
    именем, цены во вложенном объекте, кейс без награды) обязаны ВАЛИТЬ
    проверку — иначе она ничего не доказывает.

ОСТАЁТСЯ РУЧНЫМ (Hosted Test, чек-лист в REVIEWER_WALKTHROUGH.md):
    настоящий Twitch onAuthorized, обновление и истечение токена, согласие на
    передачу личности; мобильная оболочка и вёрстка; загрузка с CDN; живой
    сокет; эффекты в играх; отказы по роли канала (required_role) и кулдауны
    Bannerlord; разделы дуэлей, питомцев, гильдий, голосования, семьи и
    озвучки — кроме их цен из /api/core/config.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

HERE = Path(__file__).parent.absolute()
sys.path.insert(0, str(HERE.parent))

os.environ.setdefault("TWITCH_EXTENSION_SECRET",
                      base64.b64encode(b"frozen-client-contract-secret-32b!").decode("ascii"))
for _v, _d in (("TWITCH_OAUTH_TOKEN", "oauth:test"), ("TWITCH_CLIENT_ID", "c"),
               ("TWITCH_CLIENT_SECRET", "s"), ("TWITCH_BOT_ID", "b"),
               ("TWITCH_CHANNEL_NAME", "ch"),
               ("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890"),
               ("ADMIN_PASSWORD", "test_admin_password_for_tests_only"),
               ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(_v, _d)

FIXTURE = HERE / "fixtures" / "frozen_client_0.0.5" / "shedlink-0.0.5.zip"
ZIP_SHA256 = "6f7e115bfd8bdabbd254a4c1f42cf730961d56f06da0523161d3a54ab43da253"
HARNESS = HERE / "frozen_client_harness.mjs"

CH = 98319857
USER = "alice"
TWITCH_UID = "424242"
OPAQUE = "Ualice0000"
START = 50000
TRAIT = "Nudist"
GENE = "Hair_Snow"

_failures: list = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}" + (f" — {detail}" if detail else "")
        _failures.append(msg)
        print(msg)


# ── запросы и ответы настоящих обработчиков ─────────────────────────────────
def json_request(path: str, payload: dict, method: str = "POST"):
    from starlette.requests import Request
    body = json.dumps(payload).encode("utf-8")
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "http_version": "1.1", "method": method, "scheme": "https",
        "path": path, "raw_path": path.encode("ascii", "ignore"), "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345), "server": ("test", 443),
    }, receive)


def mint_jwt() -> str:
    """Подпись тем же ключом и тем же разбором, что в resolve_twitch_token."""
    import jwt
    raw = os.environ["TWITCH_EXTENSION_SECRET"].replace("-", "+").replace("_", "/")
    raw += "=" * ((4 - len(raw) % 4) % 4)
    return jwt.encode({"exp": int(time.time()) + 3600, "user_id": TWITCH_UID,
                       "opaque_user_id": OPAQUE, "channel_id": str(CH), "role": "viewer"},
                      base64.b64decode(raw), algorithm="HS256")


def as_viewer(user):
    """Подмена проверки JWT — как у настоящей: зритель плюс канал в контексте."""
    import dependencies
    import rimworld
    import routes.cases as rc
    import routes.notices as rn
    import routes.shedcolony as rs
    import routes.viewer as rv

    def _user(_r):
        dependencies.set_request_channel_id(CH)
        return (user, CH) if user else None

    def _channel(_r):
        dependencies.set_request_channel_id(CH)
        return CH

    for m in (rv, rc, rn, rs, rimworld):
        m.require_jwt_user = _user
    rimworld.require_jwt_channel = _channel


def game_on_air(on: bool):
    import module_liveness
    module_liveness._cache.pop((CH, "rimworld"), None)
    if on:
        module_liveness._cache[(CH, "rimworld")] = time.time()


def as_json(resp) -> dict:
    if isinstance(resp, dict):
        return resp
    return json.loads(resp.body)


async def real_resolve(body):
    import routes.misc as misc
    return as_json(await misc.resolve_twitch_token(
        json_request("/api/user/resolve-twitch-token", body)))


async def real_config(tts=None, divorce=None):
    import config
    from routes.misc import core_config
    saved_tts, saved_family = config.TTS_COST, dict(config.FAMILY_CONFIG)
    try:
        if tts is not None:
            config.TTS_COST = tts
        if divorce is not None:
            config.FAMILY_CONFIG["divorce_cost"] = divorce
        return as_json(await core_config())
    finally:
        config.TTS_COST = saved_tts
        config.FAMILY_CONFIG.clear()
        config.FAMILY_CONFIG.update(saved_family)


async def real_stats(user=USER):
    import routes.viewer as rv
    as_viewer(user)
    try:
        return as_json(await rv.viewer_stats(user or "nobody",
                                             json_request(f"/api/viewer/stats/{user}", {}, "GET")))
    finally:
        as_viewer(USER)


async def real_catalog():
    import rimworld
    as_viewer(USER)
    return as_json(await rimworld.get_catalog(
        json_request("/api/rimworld/catalog", {}, "GET"), username=USER))


async def real_buy(kind, body):
    import rimworld
    as_viewer(USER)
    handler = rimworld.buy_trait if kind == "trait" else rimworld.buy_gene
    return as_json(await handler(json_request(f"/api/rimworld/buy-{kind}", body)))


async def real_cases(user=USER):
    import routes.cases as rc
    as_viewer(user)
    try:
        return as_json(await rc.viewer_cases(json_request("/api/viewer/cases", {}, "GET")))
    finally:
        as_viewer(USER)


async def real_case_open(body):
    import routes.cases as rc
    as_viewer(USER)
    return as_json(await rc.viewer_case_open(json_request("/api/viewer/case/open", body)))


async def real_notices():
    import routes.notices as rn
    as_viewer(USER)
    return as_json(await rn.get_notices(json_request("/api/notices", {}, "GET")))


async def real_ack(body):
    import routes.notices as rn
    as_viewer(USER)
    return as_json(await rn.ack_notices(json_request("/api/notices/ack", body)))


async def real_action(body, user=USER):
    import routes.shedcolony as rs
    as_viewer(user)
    try:
        return as_json(await rs.shedcolony_buy_action(json_request("/api/shedcolony/action", body)))
    finally:
        as_viewer(USER)


async def points_of(db, user=USER):
    async with db._connect() as conn:
        cur = await conn.execute("SELECT points FROM viewers WHERE channel_id=? AND username=?",
                                 (CH, user))
        row = await cur.fetchone()
    return row[0] if row else None


# ── стенд ────────────────────────────────────────────────────────────────────
def run_client(client_dir: str, scenarios: list):
    node = shutil.which("node")
    with tempfile.TemporaryDirectory() as td:
        sp, op = Path(td) / "scenarios.json", Path(td) / "out.json"
        sp.write_text(json.dumps(scenarios, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run([node, str(HARNESS), client_dir, str(sp), str(op)],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=600)
        if proc.returncode != 0:
            raise RuntimeError("стенд упал: " + (proc.stderr or proc.stdout)[-1500:])
        out = json.loads(op.read_text(encoding="utf-8"))
    return out["scripts"], {r["name"]: r for r in out["results"]}


def route(match, body=None, status=200, method=None):
    r = {"match": match, "body": body if body is not None else {}, "status": status}
    if method:
        r["method"] = method
    return r


def net_error(match):
    return {"match": match, "network_error": True}


def scenario(name, routes, steps, observe=None, token=""):
    return {"name": name, "routes": routes, "steps": steps, "observe": observe or {},
            "setup": f'userLogin = "{USER}"; authToken = "{token}";'}


def plus(resp: dict, **extra):
    out = copy.deepcopy(resp)
    out.update(extra)
    return out


def minus(resp: dict, *keys):
    out = copy.deepcopy(resp)
    for k in keys:
        out.pop(k, None)
    return out


def notes(r, typ=None):
    return [n for n in r["notifications"] if typ is None or n["type"] == typ]


def has_note(r, text, typ=None):
    return any(text in n["message"] for n in notes(r, typ))


def writes_to(r, el_id):
    return [w["value"] for w in r["writes"] if w["id"] == el_id]


def sent(r, match):
    for f in r["fetches"]:
        if match in f["url"]:
            return f["body"]
    return None


def errors_of(r):
    return [e for e in r["loadErrors"] + r["stepErrors"]]


# ── ожидания (каждое возвращает список провалов; пусто — совместимо) ─────────
def expect_balance(server_points):
    def f(r):
        fails = []
        if errors_of(r):
            fails.append(f"ошибки клиента: {errors_of(r)[:2]}")
        if r["observed"].get("points") != server_points:
            fails.append(f"клиент держит баланс {r['observed'].get('points')!r}, "
                         f"сервер прислал {server_points}")
        if r["observed"].get("authLost") is not False:
            fails.append("клиент решил, что вход потерян")
        if str(server_points) not in writes_to(r, "points"):
            fails.append(f"в #points не записано {server_points}: {writes_to(r, 'points')[-3:]}")
        return fails
    return f


def expect_core_price(key, fallback, want, label_write=None):
    def f(r):
        fails = []
        got = r["observed"].get("price")
        if got != want:
            fails.append(f"corePrice('{key}', {fallback}) = {got!r}, ждали {want}")
        if label_write and not any(label_write in w for w in writes_to(r, "tts-price-sub")):
            fails.append(f"подпись цены не показала {label_write}")
        if errors_of(r):
            fails.append(f"ошибки клиента: {errors_of(r)[:2]}")
        return fails
    return f


def expect_note(text, typ):
    def f(r):
        fails = []
        if not has_note(r, text, typ):
            fails.append(f"нет уведомления «{text}» ({typ}); были: "
                         f"{[(n['type'], n['message'][:60]) for n in notes(r)]}")
        if errors_of(r):
            fails.append(f"ошибки клиента: {errors_of(r)[:2]}")
        return fails
    return f


def expect_reward(reward):
    def f(r):
        digits = [re.sub(r"\D", "", n["message"]) for n in notes(r, "success")]
        fails = [] if any(str(reward) in d for d in digits) else \
            [f"награда {reward} не показана; уведомления: {[n['message'][:50] for n in notes(r)]}"]
        if errors_of(r):
            fails.append(f"ошибки клиента: {errors_of(r)[:2]}")
        return fails
    return f


def report(label, fails):
    check(label, not fails, "; ".join(fails))


async def build_db(db_path: str):
    import config
    import dependencies
    import main
    from database import Database

    db = Database(db_path)
    main.db = db
    dependencies.set_db(db)
    await db.init_pool()
    await db.init_tables()
    await main.run_migrations()
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
            "VALUES (?, 'shedoy23', 'shedoy23', 'free')", (CH,))
        for user, pts in ((USER, START), ("zero", 0), ("poor", 10)):
            await conn.execute("INSERT OR IGNORE INTO viewers (channel_id, username, points) "
                               "VALUES (?, ?, ?)", (CH, user, pts))
        await conn.commit()
    config.TESTING_BYPASS_STREAM_LIVE = False
    config.RIMWORLD_REQUIRE_STREAM_LIVE = False        # так стоит на проде
    game_on_air(True)
    return db


async def run():
    import rimworld
    from notices import add_notice_tx

    raw = FIXTURE.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    check("фикстура — ровно тот архив, что идёт в Twitch", sha == ZIP_SHA256, f"sha256 {sha}")
    if sha != ZIP_SHA256:
        return
    if not shutil.which("node"):
        check("есть node для стенда", False, "без node клиента нечем исполнить")
        return

    client_dir = tempfile.mkdtemp(prefix="frozen_client_")
    zipfile.ZipFile(FIXTURE).extractall(client_dir)
    db_path = tempfile.mktemp(suffix="_frozen_client.db")
    db = await build_db(db_path)
    try:
        import routes.misc as misc
        misc._twitch_id_cache[TWITCH_UID] = USER
        token = mint_jwt()

        # ── данные сервера ─────────────────────────────────────────────────
        base = rimworld.BASE_TRAIT_PRICE
        gene_base = getattr(rimworld, "BASE_GENE_PRICE", base)

        class _Req:
            def __init__(self, p): self._p = p
            async def json(self): return self._p

        await rimworld.receive_shop_catalog(_Req([
            {"category": "trait", "def_name": TRAIT, "label": "Нудист", "price": base,
             "base_price": base, "tech_level": "", "tooltip": "✦ Настроение без одежды"},
            {"category": "gene", "def_name": GENE, "label": "Белые волосы", "price": gene_base,
             "base_price": gene_base, "tech_level": ""},
        ]), _auth=CH)
        async with db._connect() as conn:
            for _ in range(2):
                await conn.execute(
                    "INSERT INTO cases (channel_id, username, tier, source, awarded_at) "
                    "VALUES (?, ?, 'common', 'drop', CURRENT_TIMESTAMP)", (CH, USER))
            await add_notice_tx(conn, CH, USER, "refused",
                                "Игра не забрала заявку — похоже, она была закрыта.", 150)
            await add_notice_tx(conn, CH, USER, "refused", "Это действие сейчас недоступно.", 0)
            await conn.commit()

        stats = await real_stats(USER)
        stats_zero = await real_stats("zero")
        stats_unauth = await real_stats(None)
        cfg = await real_config()
        cfg_changed = await real_config(tts=7777)
        cfg_zero = await real_config(divorce=0)
        catalog_c0 = await real_catalog()
        cases_list = await real_cases()
        cases_fail = await real_cases(None)
        notices_now = await real_notices()
        game_on_air(False)
        offline_refusal = await real_buy("trait", {"username": USER, "trait_def": TRAIT,
                                                   "degree": 0, "expected_price": base})
        game_on_air(True)
        server_points = stats["points"]
        c0_price = next(i["price"] for i in catalog_c0["items"] if i["def_name"] == TRAIT)

        find_trait = f'shopAllItems.find(i => i.def === "{TRAIT}")'
        find_gene = f'shopAllItems.find(i => i.def === "{GENE}")'
        cfg_obs = lambda k, fb: {"price": f"corePrice('{k}', {fb})"}
        st_obs = {"points": "_cachedUserPoints", "authLost": "_authLost"}
        catalog_obs = {"trait": f"({find_trait} || {{}}).price",
                       "gene": f"({find_gene} || {{}}).price"}

        # ── проход 1: всё одноходовое плюс запись запросов клиента ─────────
        batch1 = [
            scenario("load", [], [], {"core": "typeof corePrice", "state": "typeof loadUserData",
                                      "buy": "typeof ShedLink.buyAction",
                                      "cases": "typeof openCase"}),
            scenario("A1-capture", [route("/api/user/resolve-twitch-token", {"login": None})],
                     [f'getUsernameFromTwitchId("{OPAQUE}", "{token}", "{OPAQUE}")']),
            scenario("A2", [route("/api/viewer/stats/", stats)], ["loadUserData()"], st_obs),
            scenario("A3-zero", [route("/api/viewer/stats/", stats_zero)], ["loadUserData()"], st_obs),
            scenario("A4-unauth", [route("/api/viewer/stats/", stats_unauth)], ["loadUserData()"], st_obs),
            scenario("A5-optional-missing",
                     [route("/api/viewer/stats/", minus(stats, "quests", "inventory", "unopened_cases",
                                                       "income_per_min", "first_step",
                                                       "card_subtitles", "stats", "active_module"))],
                     ["loadUserData()"], st_obs),
            scenario("A6-extra", [route("/api/viewer/stats/", plus(stats, future_field={"x": [1, 2]}))],
                     ["loadUserData()"], st_obs),
            scenario("A7-network", [net_error("/api/viewer/stats/")], ["loadUserData()"], st_obs),
            scenario("B1-changed", [route("/api/core/config", cfg_changed)], ["loadCoreConfig()"],
                     cfg_obs("tts_cost", 5000)),
            scenario("B2-zero", [route("/api/core/config", cfg_zero)], ["loadCoreConfig()"],
                     cfg_obs("divorce_cost", 500)),
            scenario("B3-missing", [route("/api/core/config", minus(cfg, "guild_create_cost"))],
                     ["loadCoreConfig()"], cfg_obs("guild_create_cost", 1234)),
            scenario("B4-extra", [route("/api/core/config", plus(cfg, future_price=1))],
                     ["loadCoreConfig()"], cfg_obs("tts_cost", 5000)),
            scenario("B5-refusal", [route("/api/core/config", {"detail": "boom"}, status=500)],
                     ["loadCoreConfig()"], cfg_obs("tts_cost", 5000)),
            scenario("C1", [route("/api/rimworld/catalog", catalog_c0)], ["loadShopCatalog()"], catalog_obs),
            scenario("C3-fields",
                     [route("/api/rimworld/catalog",
                            {**catalog_c0, "future": True,
                             "items": [plus(minus(i, "tooltip", "tech_level"), future_badge="new")
                                       for i in catalog_c0["items"]]})],
                     ["loadShopCatalog()"], catalog_obs),
            scenario("C4-capture",
                     [route("/api/rimworld/catalog", catalog_c0),
                      route("/api/rimworld/buy-trait", {"success": False, "message": "capture"})],
                     ["loadShopCatalog()",
                      f'buyTrait("{TRAIT}", 0, "Нудист", {find_trait}.price)',
                      '__click("confirm-dyn-yes")'], catalog_obs),
            scenario("C5-capture",
                     [route("/api/rimworld/catalog", catalog_c0),
                      route("/api/rimworld/buy-gene", {"success": False, "message": "capture"})],
                     ["loadShopCatalog()",
                      f'buyGene("{GENE}", "Белые волосы", {find_gene}.price)',
                      '__click("confirm-dyn-yes")']),
            scenario("C6-offline",
                     [route("/api/rimworld/catalog", catalog_c0),
                      route("/api/rimworld/buy-trait", offline_refusal)],
                     ["loadShopCatalog()",
                      f'buyTrait("{TRAIT}", 0, "Нудист", {find_trait}.price)',
                      '__click("confirm-dyn-yes")']),
            scenario("D1", [route("/api/viewer/cases", cases_list)], ["loadCases()"],
                     {"ok": "!!(_casesData && _casesData.success)",
                      "n": "(_casesData && (_casesData.cases || []).length) || 0"}),
            scenario("D2-capture",
                     [route("/api/viewer/case/open", {"success": False, "message": "capture"})],
                     [f'openCase({cases_list["cases"][0]["id"]}, null)']),
            scenario("D4-list-refused", [route("/api/viewer/cases", cases_fail)], ["loadCases()"]),
            scenario("D5-notices",
                     [route("/api/notices/ack", {"success": True, "marked": 0}),
                      route("/api/notices", plus(notices_now, future=1)),
                      route("/api/viewer/stats/", stats)],
                     ["pollNotices()"]),
            scenario("E1-capture",
                     [route("/api/shedcolony/action", {"success": False, "message": "capture"})],
                     ['ShedLink.buyAction("shedcolony", "colonist.spawn", {})']),
        ]
        scripts, r1 = run_client(client_dir, batch1)

        # ── между проходами: настоящие ответы на запросы клиента ───────────
        resolve_body = sent(r1["A1-capture"], "/api/user/resolve-twitch-token")
        resolved = await real_resolve(resolve_body or {})

        trait_body = sent(r1["C4-capture"], "/api/rimworld/buy-trait")
        gene_body = sent(r1["C5-capture"], "/api/rimworld/buy-gene")
        # «Другая вкладка»: настоящая покупка по той же цене — счётчик растёт.
        other_tab = await real_buy("trait", {"username": USER, "trait_def": TRAIT,
                                             "degree": 0, "expected_price": c0_price})
        catalog_c1 = await real_catalog()
        before = await points_of(db)
        consent_refusal = await real_buy("trait", trait_body or {})
        after_refusal = await points_of(db)
        gene_success = await real_buy("gene", gene_body or {})
        after_gene = await points_of(db)

        case_body = sent(r1["D2-capture"], "/api/viewer/case/open")
        opened = await real_case_open(case_body or {})
        reopened = await real_case_open(case_body or {})

        ack_body = sent(r1["D5-notices"], "/api/notices/ack")
        acked = await real_ack(ack_body or {})
        notices_after = await real_notices()

        action_body = sent(r1["E1-capture"], "/api/shedcolony/action")
        action_ok = await real_action(action_body or {})
        # Отказ берём с ДРУГИМ client_action_id. С тем же сервер отвечает
        # «Действие уже принято» и success=true (идемпотентный повтор), и это
        # не отказ, а успех — первый прогон поймал ровно эту подмену: клиент
        # честно показал зелёный тост, а проверка ждала красный.
        refused_body = json.loads(json.dumps(action_body or {}))
        refused_body.setdefault("data", {})["client_action_id"] = "frozen-client-refusal-probe"
        action_refused = await real_action(refused_body, user="poor")

        # ── проход 2 ───────────────────────────────────────────────────────
        batch2 = [
            scenario("A1", [route("/api/user/resolve-twitch-token", resolved)],
                     [f'getUsernameFromTwitchId("{OPAQUE}", "{token}", "{OPAQUE}")'
                      '.then(v => { globalThis.__login = v; })'], {"login": "globalThis.__login"}),
            scenario("A1-fields",
                     [route("/api/user/resolve-twitch-token",
                            plus(minus(resolved, "cached"), future_field="x"))],
                     [f'getUsernameFromTwitchId("{OPAQUE}", "{token}", "{OPAQUE}")'
                      '.then(v => { globalThis.__login = v; })'], {"login": "globalThis.__login"}),
            scenario("C2-changed", [route("/api/rimworld/catalog", catalog_c1)],
                     ["loadShopCatalog()"], catalog_obs),
            scenario("C4", [route("/api/rimworld/catalog", catalog_c0),
                            route("/api/rimworld/buy-trait", consent_refusal)],
                     ["loadShopCatalog()",
                      f'buyTrait("{TRAIT}", 0, "Нудист", {find_trait}.price)',
                      '__click("confirm-dyn-yes")']),
            scenario("C5", [route("/api/rimworld/catalog", catalog_c0),
                            route("/api/rimworld/buy-gene", gene_success),
                            route("/api/viewer/stats/", stats)],
                     ["loadShopCatalog()",
                      f'buyGene("{GENE}", "Белые волосы", {find_gene}.price)',
                      '__click("confirm-dyn-yes")']),
            scenario("D2", [route("/api/viewer/case/open", opened),
                            route("/api/viewer/stats/", stats)],
                     [f'openCase({cases_list["cases"][0]["id"]}, null)']),
            scenario("D3", [route("/api/viewer/case/open", reopened)],
                     [f'openCase({cases_list["cases"][0]["id"]}, null)']),
            scenario("E1", [route("/api/shedcolony/action", plus(action_ok, future_field=1)),
                            route("/api/viewer/stats/", stats)],
                     ['ShedLink.buyAction("shedcolony", "colonist.spawn", {})']),
            scenario("E2", [route("/api/shedcolony/action", action_refused)],
                     ['ShedLink.buyAction("shedcolony", "colonist.spawn", {})']),
            scenario("E3-network-then-retry",
                     [{"match": "/api/shedcolony/action",
                       "sequence": [{"network_error": True}, {"body": action_ok}]},
                      route("/api/viewer/stats/", stats)],
                     ['ShedLink.buyAction("shedcolony", "colonist.spawn", {})',
                      'ShedLink.buyAction("shedcolony", "colonist.spawn", {})']),
            # отрицательный контроль: эти ответы НЕсовместимы — проверка обязана упасть
            scenario("N1-points-renamed",
                     [route("/api/viewer/stats/", plus(minus(stats, "points"), balance=server_points))],
                     ["loadUserData()"], st_obs),
            scenario("N2-config-nested",
                     [route("/api/core/config", {"prices": cfg_changed})], ["loadCoreConfig()"],
                     cfg_obs("tts_cost", 5000)),
            scenario("N3-case-without-reward",
                     [route("/api/viewer/case/open", minus(opened, "reward_points"))],
                     [f'openCase({cases_list["cases"][0]["id"]}, null)']),
        ]
        _, r2 = run_client(client_dir, batch2)
        r = {**r1, **r2}

        # ── проверки ───────────────────────────────────────────────────────
        print("\n[0] Клиент из архива загружается")
        check("скрипты взяты из оболочки архива", len(scripts) >= 15, f"скрипты: {scripts}")
        report("все скрипты загрузились без ошибок",
               [f"{e}" for e in r["load"]["loadErrors"]])
        report("разборщики ответов на месте",
               [f"{k}={v}" for k, v in r["load"]["observed"].items() if v != "function"])

        print("\n[1] Вход и состояние")
        check("клиент шлёт вход в форме, которую принимает сервер",
              bool(resolve_body) and resolved.get("login") == USER,
              f"тело {resolve_body}, ответ сервера {resolved}")
        report("вход: логин с сервера принят клиентом",
               [] if r["A1"]["observed"].get("login") == USER else
               [f"клиент вернул {r['A1']['observed'].get('login')!r}"])
        report("вход: без необязательного поля и с лишним — то же",
               [] if r["A1-fields"]["observed"].get("login") == USER else
               [f"клиент вернул {r['A1-fields']['observed'].get('login')!r}"])
        report("состояние: баланс с сервера", expect_balance(server_points)(r["A2"]))
        report("состояние: ноль — это ноль, а не «вход потерян»",
               expect_balance(stats_zero["points"])(r["A3-zero"]))
        unauth = r["A4-unauth"]
        report("состояние: «не опознан» не превращается в ноль",
               ([] if unauth["observed"].get("authLost") is True else ["вход не помечен потерянным"])
               + ([] if "—" in writes_to(unauth, "points") else
                  [f"в #points не прочерк: {writes_to(unauth, 'points')}"]))
        report("состояние: без необязательных полей", expect_balance(server_points)(r["A5-optional-missing"]))
        report("состояние: с лишним полем", expect_balance(server_points)(r["A6-extra"]))
        report("состояние: обрыв сети — честная ошибка, без падения",
               expect_note("Сервер недоступен", "error")(r["A7-network"]))

        print("\n[2] Цены ядра")
        report("изменённая цена доходит до клиента",
               expect_core_price("tts_cost", 5000, 7777, "7777💎")(r["B1-changed"]))
        report("допустимый ноль остаётся нулём",
               expect_core_price("divorce_cost", 500, 0)(r["B2-zero"]))
        report("отсутствующая цена — запасное число, без падения",
               expect_core_price("guild_create_cost", 1234, 1234)(r["B3-missing"]))
        report("лишнее поле не мешает", expect_core_price("tts_cost", 5000, cfg["tts_cost"])(r["B4-extra"]))
        report("отказ API — запасные числа, без падения",
               expect_core_price("tts_cost", 5000, 5000)(r["B5-refusal"]))

        print("\n[3] Каталог и согласие на цену")
        report("цена в каталоге — с сервера",
               [] if r["C1"]["observed"].get("trait") == c0_price else
               [f"клиент {r['C1']['observed'].get('trait')!r}, сервер {c0_price}"])
        c1_price = next(i["price"] for i in catalog_c1["items"] if i["def_name"] == TRAIT)
        report("изменённая прогрессивная цена доходит до клиента",
               ([] if c1_price != c0_price else ["сервер не поменял цену — сценарий не воспроизведён"])
               + ([] if r["C2-changed"]["observed"].get("trait") == c1_price else
                  [f"клиент {r['C2-changed']['observed'].get('trait')!r}, сервер {c1_price}"]))
        report("лишние и отсутствующие поля каталога не мешают",
               [] if r["C3-fields"]["observed"].get("trait") == c0_price else
               [f"клиент {r['C3-fields']['observed'].get('trait')!r}"])
        check("клиент отправляет цену, которую ПОКАЗАЛ",
              bool(trait_body) and trait_body.get("expected_price") == c0_price,
              f"тело {trait_body}")
        check("сервер понимает её и отказывает при расхождении, не списав",
              other_tab.get("success") is True
              and "Цена изменилась" in str(consent_refusal.get("message"))
              and after_refusal == before,
              f"другая вкладка {other_tab}, отказ {consent_refusal}, баланс {before}→{after_refusal}")
        report("клиент показывает отказ «Цена изменилась»",
               expect_note("Цена изменилась", "error")(r["C4"]))
        check("покупка гена по показанной цене проходит на сервере",
              gene_success.get("success") is True and after_gene < after_refusal,
              f"ответ {gene_success}, баланс {after_refusal}→{after_gene}")
        report("клиент показывает успех покупки",
               expect_note(str(gene_success.get("message", ""))[:24], "success")(r["C5"]))
        report("«игра не запущена» показывается как отказ",
               expect_note("Игра сейчас не запущена", "error")(r["C6-offline"]))

        print("\n[4] Кейсы и уведомления")
        report("список кейсов принят",
               [] if r["D1"]["observed"].get("ok") is True and r["D1"]["observed"].get("n") == 2 else
               [f"observed {r['D1']['observed']}"])
        check("клиент открывает кейс запросом, который понимает сервер",
              bool(case_body) and opened.get("success") is True, f"тело {case_body}, ответ {opened}")
        report("награда кейса показана", expect_reward(opened.get("reward_points"))(r["D2"]))
        report("повторное открытие — отказ сервера показан",
               expect_note(str(reopened.get("message", ""))[:20], "error")(r["D3"]))
        report("сбой списка кейсов показан текстом сервера",
               [] if any(str(cases_fail.get("message", "")) in w for w in writes_to(r["D4-list-refused"], "cases-grid"))
               else [f"в cases-grid: {writes_to(r['D4-list-refused'], 'cases-grid')}"])
        d5 = r["D5-notices"]
        report("уведомления показаны, возврат — с суммой",
               ([] if has_note(d5, "Игра не забрала заявку") and has_note(d5, "+150💎") else
                [f"уведомления: {[n['message'][:60] for n in notes(d5)]}"])
               + ([] if has_note(d5, "Это действие сейчас недоступно") else ["второе уведомление не показано"]))
        seeded_ids = sorted(n["id"] for n in notices_now.get("notices", []))
        check("подтверждение показа принято сервером",
              bool(ack_body) and sorted(ack_body.get("ids", [])) == seeded_ids
              and acked.get("marked") == len(seeded_ids) and not notices_after.get("notices"),
              f"ack {ack_body}, ответ {acked}, после {notices_after}")

        print("\n[5] Платные действия")
        check("клиент покупает запросом, который принимает сервер",
              bool(action_body) and action_ok.get("success") is True,
              f"тело {action_body}, ответ {action_ok}")
        report("успех показан текстом сервера",
               expect_note(str(action_ok.get("message", ""))[:20], "success")(r["E1"]))
        report("отказ сервера показан текстом сервера",
               expect_note(str(action_refused.get("message", ""))[:20], "error")(r["E2"]))
        e3 = r["E3-network-then-retry"]
        tries = [f for f in e3["fetches"] if "/api/shedcolony/action" in f["url"]]
        report("обрыв сети: ошибка показана, замок отпущен, повтор проходит",
               ([] if has_note(e3, "Ошибка сети", "error") else ["нет ошибки сети"])
               + ([] if len(tries) == 2 else [f"запросов {len(tries)} — повтор не ушёл"])
               + ([] if has_note(e3, str(action_ok.get("message", ""))[:20], "success") else
                  ["повтор не показал успех"]))

        print("\n[6] Отрицательный контроль: несовместимое обязано падать")
        neg = {
            "баланс под другим именем": expect_balance(server_points)(r["N1-points-renamed"]),
            "цены во вложенном объекте": expect_core_price("tts_cost", 5000, 7777)(r["N2-config-nested"]),
            "кейс без награды": expect_reward(opened.get("reward_points"))(r["N3-case-without-reward"]),
        }
        for label, fails in neg.items():
            check(f"«{label}» распознан как несовместимый", bool(fails),
                  "проверка промолчала на заведомо сломанном ответе — она ничего не доказывает")
    finally:
        try:
            await db._pool.close()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass
        shutil.rmtree(client_dir, ignore_errors=True)


def main() -> int:
    try:
        asyncio.run(run())
    except Exception:
        traceback.print_exc()
        return 1
    print()
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print(" ", f.strip())
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())

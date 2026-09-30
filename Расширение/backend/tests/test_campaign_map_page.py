# -*- coding: utf-8 -*-
"""Публичная карта /map/<login>: каждый канал видит только свои файлы.

Свойства:
  1. страница собирается и ссылается на файлы ИМЕННО этого канала;
  2. канал без карты, неизвестный логин и мусор в адресе — одинаковый 404;
  3. отдаются только map.json и terrain.png, путь не выходит из папки канала;
  4. два канала с картами не видят файлы друг друга (папка по channel_id).

Запуск:  python tests/test_campaign_map_page.py
"""
import asyncio
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.chdir(pathlib.Path(__file__).resolve().parent.parent)

for _k, _v in (("TWITCH_OAUTH_TOKEN", "x"), ("TWITCH_CLIENT_ID", "x"),
               ("TWITCH_CLIENT_SECRET", "x"), ("TWITCH_BOT_ID", "x"),
               ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(_k, _v)

from fastapi import HTTPException  # noqa: E402

passed = 0
failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print("  OK   %s" % msg)
    else:
        failed += 1
        print("  FAIL %s" % msg)


async def status_of(coro):
    try:
        return await coro
    except HTTPException as e:
        return e.status_code


def write_map(root, channel_id, marker):
    folder = pathlib.Path(root) / str(channel_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "map.json").write_text('{"exportedUtc":"%s"}' % marker, encoding="utf-8")
    (folder / "terrain.png").write_bytes(b"\x89PNG" + marker.encode())


async def main():
    import routes.campaign_map as cm

    root = tempfile.mkdtemp(prefix="campaign_maps_")
    os.environ["CAMPAIGN_MAP_DIR"] = root

    async def channels():
        return [{"channel_id": 111, "login": "alpha"}, {"channel_id": 222, "login": "beta"}]
    cm._list_channels = channels

    write_map(root, 111, "ALPHA")
    # Ловушка: папка, названная ЛОГИНОМ беты, с чужими данными. Сервер обязан
    # искать по channel_id, а не по тексту из адреса.
    write_map(root, "beta", "WRONG")

    page = await status_of(cm.campaign_map_page("alpha"))
    if page == 404:
        check(False, "канал с картой в папке <channel_id> получает страницу (а получил 404)")
        print("\n%d OK, %d FAIL" % (passed, failed))
        return False
    body = page.body.decode("utf-8")
    check(page.status_code == 200 and body.lstrip().startswith("<!DOCTYPE html>"), "страница канала с картой собирается")
    check('"/map/alpha/map.json?v=' in body and '"/map/alpha/terrain.png?v=' in body,
          "страница ссылается на файлы своего канала, с меткой версии против старого кэша")
    check("ALPHA" in body, "дата выгрузки из map.json канала попала на страницу")
    check("{{" not in body and "{%" not in body, "в выдаче не осталось меток шаблона")
    check((await cm.campaign_map_page("ALPHA")).status_code == 200, "логин без учёта регистра, как в Twitch")

    check(await status_of(cm.campaign_map_page("beta")) == 404, "канал без своей карты — 404 (папка-ловушка по логину не читается)")
    check(await status_of(cm.campaign_map_page("nobody")) == 404, "неизвестный логин — 404")
    for bad in ("../alpha", "alpha/..", "a" * 26, "al pha", "", "..%2F111"):
        check(await status_of(cm.campaign_map_page(bad)) == 404, "мусор в логине %r — 404" % bad)

    f = await cm.campaign_map_file("alpha", "map.json")
    check(pathlib.Path(f.path) == pathlib.Path(root) / "111" / "map.json", "map.json отдаётся из папки channel_id")
    for bad in ("../../main.py", "viewers.db", "map.json/..", "..", "terrain.PNG"):
        check(await status_of(cm.campaign_map_file("alpha", bad)) == 404, "чужое имя файла %r — 404" % bad)

    # Сглаженная карта (jpg) главнее ранней пиксельной (png), если лежат обе.
    (pathlib.Path(root) / "111" / "terrain.jpg").write_bytes(b"JPG-bytes")
    body = (await cm.campaign_map_page("alpha")).body.decode("utf-8")
    check('"/map/alpha/terrain.jpg?v=' in body, "страница берёт сглаженную terrain.jpg, когда она есть")
    fj = await cm.campaign_map_file("alpha", "terrain.jpg")
    check(fj.media_type == "image/jpeg", "terrain.jpg отдаётся как image/jpeg")

    write_map(root, 222, "BETA")
    fa = await cm.campaign_map_file("alpha", "map.json")
    fb = await cm.campaign_map_file("beta", "map.json")
    check(pathlib.Path(fb.path).read_text(encoding="utf-8").count("BETA") == 1
          and pathlib.Path(fa.path).read_text(encoding="utf-8").count("ALPHA") == 1,
          "два канала с картами получают каждый свою")
    check("BETA" in (await cm.campaign_map_page("beta")).body.decode("utf-8"), "страница беты показывает её выгрузку")

    await live_layer(cm, root)
    print("\n%d OK, %d FAIL" % (passed, failed))
    return failed == 0


async def live_layer(cm, root):
    """Живой слой: мод → адаптер → live.json своего канала → страница."""
    import json
    import yaml
    import campaign_map_store as store
    from modules._base import ModuleEnvelope
    from modules.bannerlord._adapter import BannerlordAdapter

    manifest = yaml.safe_load(open("modules/bannerlord/manifest.yaml", encoding="utf-8"))
    check("map.live_snapshot" in (manifest.get("extensions") or {}).get("events", []),
          "событие map.live_snapshot объявлено в манифесте (иначе сервер молча выбросит)")

    check(await status_of(cm.campaign_map_file("alpha", "live.json")) == 404, "пока снимков не было — live.json 404")
    check(store.store_live(333, {"parties": []}) is False and not (pathlib.Path(root) / "333").exists(),
          "канал без опубликованной карты: снимок не пишется, папка не заводится")

    hostile = {
        "day": 12.5, "secret": "x" * 100,
        "parties": [{"id": "p1", "x": 10, "y": 20, "men": 55, "login": "<b>viewer</b>", "main": True,
                     "name": "N" * 500, "evil": {"deep": 1}},
                    {"id": "nopos", "men": 5},
                    {"id": "nan", "x": float("nan"), "y": 1}]
                   + [{"id": "p%d" % i, "x": 1, "y": 1} for i in range(5000)],
        "settlements": [{"id": "town_A", "garrison": 300, "militia": 120.7, "siege": True, "extra": 1}],
    }
    adapter = BannerlordAdapter(None)
    await adapter.handle_event(111, ModuleEnvelope(id="live1", kind="event", type="map.live_snapshot",
                                                   ts=1, data=hostile))
    live_a = pathlib.Path(root) / "111" / "live.json"
    check(live_a.is_file(), "снимок канала записан в папку его channel_id")
    check(not (pathlib.Path(root) / "222" / "live.json").exists(), "чужой канал снимок не получил")
    data = json.loads(live_a.read_text(encoding="utf-8"))
    p1 = next((p for p in data["parties"] if p["id"] == "p1"), {})
    check(p1.get("men") == 55 and p1.get("main") is True and p1.get("login") == "<b>viewer</b>",
          "нужные поля отряда сохранены как есть (экранирует страница, textContent)")
    check("evil" not in p1 and "secret" not in data and len(p1.get("name", "")) == store.MAX_TEXT,
          "лишние поля отброшены, длинный текст обрезан")
    check(not any(p["id"] in ("nopos", "nan") for p in data["parties"]), "отряд без координат или с NaN отброшен")
    check(len(data["parties"]) <= store.MAX_PARTIES, "число отрядов ограничено потолком (%d)" % len(data["parties"]))
    town = data["settlements"][0]
    check(town == {"id": "town_A", "garrison": 300.0, "militia": 120.7, "siege": True},
          "у поселения — гарнизон, ополчение, осада; лишнее отброшено")
    check(await status_of(cm.campaign_map_file("alpha", "live.json")) != 404, "страница получает live.json своего канала")


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)

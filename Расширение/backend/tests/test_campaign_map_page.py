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
    check('"/map/alpha/map.json"' in body and '"/map/alpha/terrain.png"' in body, "страница ссылается на файлы своего канала")
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

    write_map(root, 222, "BETA")
    fa = await cm.campaign_map_file("alpha", "map.json")
    fb = await cm.campaign_map_file("beta", "map.json")
    check(pathlib.Path(fb.path).read_text(encoding="utf-8").count("BETA") == 1
          and pathlib.Path(fa.path).read_text(encoding="utf-8").count("ALPHA") == 1,
          "два канала с картами получают каждый свою")
    check("BETA" in (await cm.campaign_map_page("beta")).body.decode("utf-8"), "страница беты показывает её выгрузку")

    print("\n%d OK, %d FAIL" % (passed, failed))
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)

"""Публичная карта кампании канала: https://shedoy23.ru/map/<login> (30.09.2026).

Карта нарисована из данных игры (пробник MapExportProbe + build-site.py), а не
снята с экрана. Файлы канала лежат в `<CAMPAIGN_MAP_DIR>/<channel_id>/`:
`map.json` (поселения, фракции) и `terrain.png` (рельеф). Кладутся вручную;
позже их сможет присылать мод. Нет файлов у канала — 404, как и у неизвестного
логина: наружу не сообщаем, зарегистрирован ли канал.
"""
import html
import json
import pathlib
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from campaign_map_store import channel_dir
from dependencies import get_db
from routes.streamer import _render_template

router = APIRouter(tags=["campaign-map"])

_LOGIN = re.compile(r"^[a-z0-9_]{1,25}$")  # правила логина Twitch
TERRAIN_FILES = ("terrain.jpg", "terrain.png")  # сглаженная (jpg) или ранняя пиксельная (png)
SERVED_FILES = ("map.json", "live.json") + TERRAIN_FILES  # live.json — когда мод присылает снимки
_MEDIA = {".json": "application/json", ".jpg": "image/jpeg", ".png": "image/png"}


def _terrain(folder: pathlib.Path):
    return next((folder / n for n in TERRAIN_FILES if (folder / n).is_file()), None)


async def _list_channels() -> list:
    return await get_db().list_channels()


async def _map_dir(login: str) -> pathlib.Path:
    login = (login or "").lower()
    if not _LOGIN.match(login):
        raise HTTPException(status_code=404)
    for ch in await _list_channels():
        if (ch.get("login") or "").lower() == login:
            # Папка — по channel_id из базы, не по тексту из адреса: логин
            # только ищет канал и в путь файловой системы не попадает.
            folder = channel_dir(ch["channel_id"])
            if (folder / "map.json").is_file() and _terrain(folder):
                return folder
            break
    raise HTTPException(status_code=404)


@router.get("/map/{login}", response_class=HTMLResponse)
async def campaign_map_page(login: str):
    folder = await _map_dir(login)
    try:
        exported = json.loads((folder / "map.json").read_text(encoding="utf-8")).get("exportedUtc")
    except (OSError, ValueError):
        raise HTTPException(status_code=404)
    login = login.lower()
    terrain = _terrain(folder)
    # Метка версии в адресе: после замены карты браузер не смешает новый map.json
    # со старой картинкой другого размера (кэш файлов — 5 минут).
    ver = "%d" % max((folder / "map.json").stat().st_mtime, terrain.stat().st_mtime)
    # Пробник пишет ISO-время ("2026-09-30T15:57:14.85Z") — на странице дата по-русски.
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(exported or ""))
    if m:
        exported = "выгрузка %s.%s.%s" % (m.group(3), m.group(2), m.group(1))
    return HTMLResponse(_render_template(
        "campaign_map.html",
        title=html.escape(login),
        data_url=json.dumps(f"/map/{login}/map.json?v={ver}"),
        image_url=json.dumps(f"/map/{login}/{terrain.name}?v={ver}"),
        live_url=json.dumps(f"/map/{login}/live.json"),
        exported=html.escape(str(exported or "")),
    ))


@router.get("/map/{login}/{name}")
async def campaign_map_file(login: str, name: str):
    if name not in SERVED_FILES:
        raise HTTPException(status_code=404)
    folder = await _map_dir(login)
    if not (folder / name).is_file():
        raise HTTPException(status_code=404)
    media = _MEDIA[pathlib.Path(name).suffix]
    # Живой слой меняется раз в 15 с — кэш короче интервала опроса страницы.
    cache = "no-cache" if name == "live.json" else "public, max-age=300"
    return FileResponse(folder / name, media_type=media, headers={"Cache-Control": cache})

"""Публичная карта кампании канала: https://shedoy23.ru/map/<login> (30.09.2026).

Карта нарисована из данных игры (пробник MapExportProbe + build-site.py), а не
снята с экрана. Файлы канала лежат в `<CAMPAIGN_MAP_DIR>/<channel_id>/`:
`map.json` (поселения, фракции) и `terrain.png` (рельеф). Кладутся вручную;
позже их сможет присылать мод. Нет файлов у канала — 404, как и у неизвестного
логина: наружу не сообщаем, зарегистрирован ли канал.
"""
import html
import json
import os
import pathlib
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from dependencies import get_db
from routes.streamer import _render_template

router = APIRouter(tags=["campaign-map"])

_LOGIN = re.compile(r"^[a-z0-9_]{1,25}$")  # правила логина Twitch
_BACKEND = pathlib.Path(__file__).resolve().parent.parent
MAP_FILES = ("map.json", "terrain.png")


def map_root() -> pathlib.Path:
    return pathlib.Path(os.getenv("CAMPAIGN_MAP_DIR") or (_BACKEND / "campaign_maps"))


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
            folder = map_root() / str(int(ch["channel_id"]))
            if all((folder / name).is_file() for name in MAP_FILES):
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
    return HTMLResponse(_render_template(
        "campaign_map.html",
        title=html.escape(login),
        data_url=json.dumps(f"/map/{login}/map.json"),
        image_url=json.dumps(f"/map/{login}/terrain.png"),
        exported=html.escape(str(exported or "")),
    ))


@router.get("/map/{login}/{name}")
async def campaign_map_file(login: str, name: str):
    if name not in MAP_FILES:
        raise HTTPException(status_code=404)
    folder = await _map_dir(login)
    media = "application/json" if name.endswith(".json") else "image/png"
    return FileResponse(folder / name, media_type=media, headers={"Cache-Control": "public, max-age=300"})

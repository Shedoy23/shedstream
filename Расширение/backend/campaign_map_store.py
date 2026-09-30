"""Файлы карты кампании канала: `<CAMPAIGN_MAP_DIR>/<channel_id>/` (30.09.2026).

map.json + terrain.png — статичная основа (build-site.py, кладутся руками).
live.json — живой слой: мод шлёт `map.live_snapshot` раз в 15 с, здесь он
чистится (только известные поля, обрезанный текст, потолки) и пишется атомарно.
Пишем только каналу, у которого карта уже опубликована: остальным папок не заводим.
"""
import json
import os
import pathlib
import time

_BACKEND = pathlib.Path(__file__).resolve().parent
MAX_PARTIES = 3000
MAX_SETTLEMENTS = 2000
MAX_TEXT = 80

_PARTY_TEXT = ("id", "name", "hero", "login", "clan", "f", "color", "armyLeader", "armyName",
               "inside", "besieging", "target", "behavior")
_PARTY_NUM = ("x", "y", "men", "wounded", "prisoners", "armyMen")
_SETTLEMENT_TEXT = ("id", "f", "factionName", "color", "clan", "raided")
_SETTLEMENT_NUM = ("garrison", "militia")


def map_root() -> pathlib.Path:
    return pathlib.Path(os.getenv("CAMPAIGN_MAP_DIR") or (_BACKEND / "campaign_maps"))


def channel_dir(channel_id: int) -> pathlib.Path:
    return map_root() / str(int(channel_id))


def _text(v):
    return None if v is None else str(v)[:MAX_TEXT]


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return None
    return round(float(v), 1)


def _clean(item, text_keys, num_keys, bool_keys):
    if not isinstance(item, dict):
        return None
    out = {k: _text(item.get(k)) for k in text_keys if item.get(k) is not None}
    out.update({k: _num(item.get(k)) for k in num_keys if _num(item.get(k)) is not None})
    out.update({k: True for k in bool_keys if item.get(k) is True})
    return out if out.get("id") else None


def clean_live(data) -> dict:
    """Оставить только то, что рисует страница. Мусор и лишнее отбрасываются."""
    data = data if isinstance(data, dict) else {}
    parties = data.get("parties") if isinstance(data.get("parties"), list) else []
    settlements = data.get("settlements") if isinstance(data.get("settlements"), list) else []
    parties = [p for p in (_clean(p, _PARTY_TEXT, _PARTY_NUM, ("main",)) for p in parties[:MAX_PARTIES])
               if p and "x" in p and "y" in p]
    settlements = [s for s in (_clean(s, _SETTLEMENT_TEXT, _SETTLEMENT_NUM, ("siege",))
                               for s in settlements[:MAX_SETTLEMENTS]) if s]
    return {"updatedUnix": int(time.time()), "day": _num(data.get("day")),
            "parties": parties, "settlements": settlements}


def store_live(channel_id: int, data) -> bool:
    """Записать живой слой канала. False — у канала нет опубликованной карты."""
    folder = channel_dir(channel_id)
    if not (folder / "map.json").is_file():
        return False
    tmp = folder / "live.json.tmp"
    tmp.write_text(json.dumps(clean_live(data), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, folder / "live.json")
    return True

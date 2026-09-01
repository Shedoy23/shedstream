"""
routes/module_api.py — Module API HTTP endpoints (этап 3 steps 1+2+3).

Реализует подмножество docs/MODULE_API.md §3.1 (REST long-poll transport):
  - GET  /v1/modules                 — list discovered modules
  - GET  /v1/module/<id>/info        — manifest dump (debug/admin)
  - POST /v1/module/<id>/hello       — handshake (§6)
  - POST /v1/module/<id>/events      — приём событий от connector'а (§7)
  - GET  /v1/module/<id>/actions     — long-poll outbox для actions (§3.1, §8)
  - POST /v1/module/<id>/ack         — connector'ский ACK на исполненный action

Не реализовано (Step 4+):
  - Catalogs publish/consume через module.catalog_update + module-shop endpoints
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import Deque, Set

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from dependencies import get_db

log = logging.getLogger("rimlink.module_api")
from modules._base import ModuleEnvelope
from modules._loader import get_module, list_modules

router = APIRouter()


# Public-gate (2026-07-02): debug/info-эндпоинты раскрывают конфигурацию всех
# модулей (события/действия/каталоги/кол-во каналов) — разведка для атакующего.
# У них НЕТ вызывающих (ни фронт, ни моды). Прячем за env-флагом (по умолчанию
# 404). Включить для отладки: EXPOSE_MODULE_DEBUG=1.
def _module_debug_enabled() -> bool:
    return os.getenv("EXPOSE_MODULE_DEBUG", "0") == "1"


@router.get("/v1/modules", include_in_schema=False)
async def list_modules_endpoint():
    """Список зарегистрированных модулей (debug; gated env EXPOSE_MODULE_DEBUG)."""
    if not _module_debug_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return {
        "modules": [
            {
                "id": m.manifest.id,
                "version": m.manifest.version,
                "display_name": m.manifest.display_name,
                "description": m.manifest.description,
                "events": m.manifest.events + m.manifest.extension_events,
                "actions": m.manifest.actions + m.manifest.extension_actions,
                "catalogs": m.manifest.catalogs,
                "active_channels": len(m._active_channels),
            }
            for m in list_modules()
        ]
    }


@router.get("/v1/module/{module_id}/info", include_in_schema=False)
async def module_info(module_id: str):
    if not _module_debug_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    adapter = get_module(module_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "module_not_found", "module_id": module_id},
        )
    m = adapter.manifest
    return {
        "id": m.id,
        "version": m.version,
        "core_api_version": m.core_api_version,
        "display_name": m.display_name,
        "description": m.description,
        "icon": m.icon,
        "events": m.events,
        "actions": m.actions,
        "extensions": {
            "events": m.extension_events,
            "actions": m.extension_actions,
        },
        "catalogs": m.catalogs,
        "ui_slots": m.ui_slots,
    }


@router.post("/v1/module/{module_id}/hello", include_in_schema=False)
async def module_hello(module_id: str, request: Request):
    """Handshake (§6 спеки). Connector прислал manifest digest + version,
    core отвечает welcome'ом со списком capabilities.

    Auth: Bearer module-token (как все module-endpoint'ы). channel_id берётся
    ИЗ токена — body.channel_id игнорируется.
    """
    adapter = get_module(module_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "module_not_found", "module_id": module_id},
        )

    # AUDIT 2026-05-29 (FULL_AUDIT fix #2): раньше hello НЕ требовал auth и
    # доверял body.channel_id → любой мог спуфить online-статус / session
    # side-effects чужого канала. Теперь channel_id authoritative из module-token.
    channel_id = await _verify_module_request(request, module_id)

    try:
        body = await request.json()
    except Exception:
        body = {}

    connector_version = str(body.get("connector_version", "unknown"))
    manifest_digest = str(body.get("manifest_digest", ""))

    welcome = await adapter.on_hello(channel_id, connector_version, manifest_digest)
    return JSONResponse({"status": "welcome", **welcome})


@router.post("/v1/module/{module_id}/auth-check", include_in_schema=False)
async def module_auth_check(module_id: str, request: Request):
    """Validate connector credentials without creating heartbeat/liveness state.

    Manager uses this after writing game config. A successful response proves
    only backend reachability and token scope; the real game must still produce
    its own heartbeat before Technical Ready.
    """
    if not get_module(module_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "module_not_found", "module_id": module_id},
        )
    await _verify_module_request(request, module_id)
    response = JSONResponse({"status": "ok", "module_id": module_id})
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/v1/module/{module_id}/status", include_in_schema=False)
async def module_runtime_status(module_id: str, request: Request):
    """Read real connector liveness without creating a heartbeat."""
    if not get_module(module_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "module_not_found", "module_id": module_id},
        )
    channel_id = await _verify_module_request(request, module_id)
    import module_liveness
    last_seen = await module_liveness.last_seen(get_db(), channel_id, module_id)
    age_seconds = max(0, int(time.time() - last_seen)) if last_seen else None
    response = JSONResponse({
        "status": "ok",
        "module_id": module_id,
        "online": age_seconds is not None
        and age_seconds < module_liveness.ONLINE_WINDOW_SEC,
        "last_seen_at": last_seen or None,
        "age_seconds": age_seconds,
        "online_window_seconds": module_liveness.ONLINE_WINDOW_SEC,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


# ── Этап 3 step 2: events endpoint ───────────────────────────────────────────

# In-memory dedup ring. Хранит последние N envelope id'ов чтобы повтор от
# connector'а (после reconnect / retry) не приводил к double-processing.
# Per-channel ring чтобы не блокировать каналы взаимными retry'ями.
_DEDUP_RING_SIZE = 5000
# Потолок на число конвертов в одном POST /events. Живой мод присылает единицы
# за раз; предел нужен не для него, а против запроса по утёкшему токену канала
# (см. комментарий у проверки). 2026-07-30, аудит §5.
MAX_ENVELOPES_PER_BATCH = 200

# Ключ — (channel_id, module_id), НЕ один channel_id.
# 2026-08-02, внешний разбор модульного ядра: кольцо было per-channel, поэтому
# два модуля одного канала, приславшие конверт с одинаковым id, затирали друг
# друга — второй молча объявлялся дубликатом и НЕ обрабатывался. Сейчас каналов
# с двумя живыми модулями нет, так что дефект спал; проснулся бы ровно в день,
# когда рядом с Bannerlord встанет shedcolony или RimWorld, и выглядел бы как
# «событие пропало без следа». Id конвертов выдаёт коннектор, и требовать от
# двух независимых модов глобальной уникальности мы не можем.
#
# ⚠️ Кольцо живёт В ПАМЯТИ процесса: рестарт его теряет, а при нескольких
# воркерах у каждого своё. Оба ограничения известны и приняты (UVICORN_WORKERS=1,
# а после рестарта повтор конверта максимум исполнится второй раз — от этого
# защищает идемпотентность самих обработчиков). Перенос в БД — в DEFERRED,
# вместе с lease-моделью.
_processed_envelopes: dict = {}  # (channel_id, module_id) → (Set[id], Deque[id])


def _dedup_key(channel_id: int, module_id: str) -> tuple:
    return (channel_id, module_id or "")


def _forget_envelope(channel_id: int, env_id: str, module_id: str = "") -> None:
    """Забыть конверт, чтобы повтор МОГ быть обработан.

    2026-07-31 ВНЕШНИЙ АУДИТ (находка 4). `_is_duplicate_envelope` помечает id
    увиденным В МОМЕНТ ПРОВЕРКИ — то есть ДО вызова обработчика. Если
    обработчик падал (сбой БД, исключение в адаптере), конверт навсегда
    считался обработанным: повтор с тем же id получал `duplicate: true,
    success: true` и НЕ исполнялся.

    Цена ошибки конкретная: `action.failed` — это заявка на ВОЗВРАТ денег. Мод
    шлёт её fire-and-forget, одним запросом, без повторов. Одного сбоя хватало,
    чтобы возврат исчез, а списание осталось.

    Поэтому при неудачной обработке конверт забываем — тогда повтор (мода,
    сторожа или человека) сработает штатно, а идемпотентность возврата
    обеспечит маркер `REFUNDED:`.
    """
    pair = _processed_envelopes.get(_dedup_key(channel_id, module_id))
    if not pair or not env_id:
        return
    seen, q = pair
    if env_id in seen:
        seen.discard(env_id)
        try:
            q.remove(env_id)
        except ValueError:
            pass


def _is_duplicate_envelope(channel_id: int, env_id: str,
                           module_id: str = "") -> bool:
    """True если уже видели этот id ОТ ЭТОГО ЖЕ МОДУЛЯ за последние
    _DEDUP_RING_SIZE сообщений."""
    if not env_id:
        return False  # пустой id не дедуплицируем — caller'у виднее
    key = _dedup_key(channel_id, module_id)
    pair = _processed_envelopes.get(key)
    if pair is None:
        pair = (set(), deque())
        _processed_envelopes[key] = pair
    seen, q = pair
    if env_id in seen:
        return True
    seen.add(env_id)
    q.append(env_id)
    if len(q) > _DEDUP_RING_SIZE:
        old = q.popleft()
        seen.discard(old)
    return False


def _extract_bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


@router.post("/v1/module/{module_id}/events", include_in_schema=False)
async def module_events(module_id: str, request: Request):
    """Принимает массив envelope'ов от connector'а. Per docs/MODULE_API.md §7.

    Auth: Authorization: Bearer <module-token>. Token issuance — через
    GET /api/streamer/module-token (M4.4 dashboard, требует session cookie).

    Body: {channel_id: int, envelopes: [{id, kind, type, ts, data}]}.
    Caller channel_id должен совпадать с token.channel_id (защита от
    cross-channel injection через cтянутый токен с другого канала).

    Returns: {status: "ok", acks: [{id, success, error?}]}.
    """
    adapter = get_module(module_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "module_not_found", "module_id": module_id},
        )

    # 1. Auth
    # Sprint 5.31 #45e (audit MED-8) — collapse trio of auth failures
    # (missing_auth / invalid_token / module_id_mismatch / channel_id_mismatch
    # ниже) в ОДИН error response. Раньше attacker мог распознать «какой
    # именно из leaked токенов в его руках» по различающимся error messages
    # (timing oracle). Теперь returned-side identical; reason всё ещё
    # логируется внутрь для debugging.
    _AUTH_FAILED = {"status": "auth_failed",
                    "message": "Module-token missing, expired or wrong channel"}
    token_channel_id = await _verify_module_request(request, module_id)

    # 2. Body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "bad_json"},
        )
    raw_cid = body.get("channel_id") or 0
    try:
        body_channel_id = int(raw_cid)
    except (TypeError, ValueError):
        body_channel_id = 0
    if body_channel_id != token_channel_id:
        # Sprint 5.31 #45e (audit MED-8) — same _AUTH_FAILED response для
        # неотличимости от прочих auth fails (timing oracle protection).
        log.warning("[module_api] auth_failed: body channel_id=%s ≠ token=%s",
                    body_channel_id, token_channel_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_FAILED)
    channel_id = body_channel_id

    # Отличаем «пустая пачка» от «тело не распознано». Разница дорогая:
    # 2026-08-02 я сам отправил конверты под ключом `events` вместо `envelopes`
    # — бэкенд ответил `status: ok` с пустым acks, конверты молча пропали, а
    # прогон аудита из-за этого отрапортовал 12 несуществующих денежных
    # дефектов. Тот, кто пишет коннектор, попадёт в ту же яму: ответ «ок» на
    # запрос, который ничего не сделал, — худший из возможных.
    has_key = "envelopes" in body
    envelopes_raw = body.get("envelopes") or []
    if not isinstance(envelopes_raw, list):
        # Fallback: одиночный envelope без wrapper'а
        envelopes_raw = [body] if body.get("type") else []
        has_key = has_key or bool(body.get("type"))
    if not envelopes_raw:
        if has_key:
            return {"status": "ok", "acks": []}   # честно пустая пачка
        log.warning("[module_api] no_envelopes ch=%s module=%s keys=%s",
                    channel_id, module_id, sorted(body.keys())[:8])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "no_envelopes",
                    "message": "Ожидается поле 'envelopes' (список конвертов) "
                               "или одиночный конверт с полем 'type'. "
                               "Ничего не обработано.",
                    "got_keys": sorted(body.keys())[:8]})

    # 2026-07-30 (аудит спеки §5, вопрос «есть ли ограничение на размер») —
    # ПОТОЛОК НА ПАКЕТ. Его не было вовсе: каждый конверт проверяется и
    # дедуплицируется по отдельности, но их число не ограничивалось ничем, кроме
    # `client_max_body_size 20m` на nginx. То есть один запрос по токену канала
    # мог принести десятки тысяч конвертов и занять единственное ядро VDS
    # (1 CPU / 1 ГБ) на всё время обработки — при том что rate-limit к
    # module-эндпоинтам не применяется (middleware ставит только заголовки).
    # Живой мод шлёт единицы конвертов за раз; 200 — запас на два порядка.
    if len(envelopes_raw) > MAX_ENVELOPES_PER_BATCH:
        log.warning("[module_api] batch_too_large ch=%s module=%s envelopes=%d",
                    channel_id, module_id, len(envelopes_raw))
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"status": "batch_too_large",
                    "max": MAX_ENVELOPES_PER_BATCH,
                    "got": len(envelopes_raw)},
        )

    # Присланное событие — тоже признак живого мода. Для модулей без опроса
    # заданий (не Bannerlord) это единственный сигнал, поэтому он здесь.
    try:
        import module_liveness
        await module_liveness.touch(get_db(), channel_id, module_id)
    except Exception:
        pass

    # 3. Dispatch each envelope
    acks: list = []
    for raw in envelopes_raw:
        if not isinstance(raw, dict):
            acks.append({"id": "?", "success": False, "error": "envelope_not_object"})
            continue
        env = ModuleEnvelope(
            id=str(raw.get("id") or ""),
            kind=str(raw.get("kind") or "event"),
            type=str(raw.get("type") or ""),
            ts=int(raw.get("ts") or 0),
            data=raw.get("data") or {},
        )
        if not env.type:
            acks.append({"id": env.id, "success": False, "error": "type_required"})
            continue
        # Manifest validation: тип события должен быть declared в manifest'е
        if not adapter.manifest.supports_event(env.type):
            acks.append({"id": env.id, "success": False, "error": "event_not_in_manifest"})
            continue
        # Dedup
        if _is_duplicate_envelope(channel_id, env.id, module_id):
            acks.append({"id": env.id, "success": True, "duplicate": True})
            continue
        # Lifecycle hooks для module.* events
        try:
            if env.type == "module.session_start":
                await adapter.on_session_start(channel_id, env.data)
            elif env.type == "module.session_end":
                await adapter.on_session_end(channel_id, env.data)
            # Все custom + remaining standard события идут в handle_event
            # (включая module.heartbeat — adapter сам решает no-op'ить или нет)
            await adapter.handle_event(channel_id, env)
            acks.append({"id": env.id, "success": True})
        except Exception as e:
            # Sprint 5.29 audit fix #34: было лог только в ack response — сервер
            # сам ничего не печатал → если supervisorctl tail смотришь,
            # не увидишь что envelope failed. Теперь logger.exception
            # с stack trace в stderr.
            import logging
            logging.getLogger("rimlink.module_api").exception(
                "[event handler] channel=%s envelope_id=%s type=%s failed: %s",
                channel_id, env.id, env.type, e)
            # Обработка не удалась → конверт НЕ считается обработанным, иначе
            # повтор объявят дубликатом и заявка на возврат исчезнет навсегда
            # (внешний аудит 31.07, находка 4).
            _forget_envelope(channel_id, env.id, module_id)
            acks.append({"id": env.id, "success": False,
                         "error": f"{type(e).__name__}: {e}"})

    return {"status": "ok", "acks": acks}


# ── Этап 3 step 3: actions outbox ────────────────────────────────────────────

# Long-poll параметры. Connector делает GET с timeout'ом ~30 сек; мы держим
# соединение до этого предела, проверяя БД каждые _POLL_INTERVAL.
_LONG_POLL_TIMEOUT_SEC = 25
# Sprint 5.33 IMPROV-2 (friend feedback): action delivery responsiveness.
# Раньше = 1.0s — viewer's purchase появлялся в-game с latency 0-1000ms.
# Снижено до 0.3s — sub-second responsiveness (avg ~150ms latency). Cost:
# 3× CPU на idle long-polls (negligible на нашем scale — 1-5 streamers).
# Если scale пойдёт до 100+ concurrent streamers — повысить обратно к 1.0.
_LONG_POLL_INTERVAL_SEC = 0.3
_BATCH_LIMIT = 50


async def _verify_module_request(request: Request, module_id: str) -> int:
    """Helper: validate Authorization + module match. Возвращает channel_id из
    токена или поднимает HTTPException. Используется actions/ack endpoints'ами.

    Sprint 5.31 #45e (audit MED-8) — все 3 failure paths возвращают
    одинаковый response чтобы attacker не мог через 401-vs-403 различать
    «leaked токен с правильного канала» vs «leaked с чужого канала».
    Reason пишется в лог (WARNING) для дебага.
    """
    _AUTH_FAILED = {"status": "auth_failed",
                    "message": "Module-token missing, expired or wrong channel"}
    auth = request.headers.get("Authorization", "")
    if auth[:7].lower() != "bearer ":
        log.warning("[module_api] auth_failed: missing Bearer (module=%s)", module_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_FAILED)
    token = auth[7:].strip()
    if token.startswith("slmod_v1."):
        import manager_auth
        try:
            async with get_db()._connect() as conn:
                claims = await manager_auth.verify_module_credential(
                    conn, token, module_id
                )
        except manager_auth.ManagerAuthUnavailable:
            claims = None
    else:
        # Legacy short-lived HMAC token remains valid during Manager rollout.
        from routes.streamer import verify_module_token
        claims = verify_module_token(token)
    if not claims:
        log.warning("[module_api] auth_failed: invalid/expired token (module=%s)",
                    module_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_FAILED)
    if claims["module_id"] != module_id:
        log.warning("[module_api] auth_failed: module_id mismatch "
                    "(token=%s route=%s)", claims["module_id"], module_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_FAILED)
    return int(claims["channel_id"])


@router.get("/v1/module/{module_id}/actions", include_in_schema=False)
async def module_actions_poll(module_id: str, request: Request):
    """Long-poll outbox для actions. Connector вызывает с `?since=<id>` где id
    — последний полученный PK. Если есть queued — возвращает batch, помечает
    их dispatched. Если нет — long-poll ждёт до 25 сек проверяя каждую секунду.

    Returns: {actions: [{id, action_id, type, data, created_at}], cursor: int}
    cursor — монотонный max(previous cursor, id из batch). Retry может иметь
    старый PK, поэтому сам по себе его id не должен откатывать cursor.
    Пустой actions+timeout = таймаут long-poll'а; connector ре-запросит.
    """
    adapter = get_module(module_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "module_not_found", "module_id": module_id},
        )
    channel_id = await _verify_module_request(request, module_id)

    # Online status flicker fix: mod active = long-poll keeps coming. Mark
    # last_seen на каждый poll start (как heartbeat) — UI badge не будет
    # пугать "оффлайн" между event'ами. Только для bannerlord — обобщить
    # позже (нужен generic last_seen helper в _base).
    # 2026-08-06 (фаза 1, решение владельца): отметка теперь для ЛЮБОГО модуля
    # и переживает перезапуск бэкенда. Раньше здесь стоял `if module_id ==
    # "bannerlord"` с припиской «обобщить позже» — из-за него тихий мод другой
    # игры считался бы мёртвым, а по этой отметке теперь решается, предлагать
    # ли зрителю платные действия.
    try:
        import module_liveness
        await module_liveness.touch(get_db(), channel_id, module_id)
    except Exception:
        pass
    if module_id == "bannerlord":
        try:
            from modules.bannerlord._adapter import update_last_seen
            update_last_seen(channel_id)
        except Exception:
            pass

    raw_since = request.query_params.get("since", "0")
    try:
        since_id = max(0, int(raw_since))
    except ValueError:
        since_id = 0

    db = get_db()
    deadline = time.time() + _LONG_POLL_TIMEOUT_SEC
    while True:
        # 2026-09-01 — аварийная пауза стримера: пока она взведена, мод не
        # получает НИЧЕГО, включая задания, поставленные до нажатия кнопки.
        # Долгий опрос при этом не рвём: мод продолжает ждать как обычно и не
        # начинает долбить сервер в цикле. Снятие паузы вернёт очередь моду —
        # молча выбрасывать оплаченное хуже, чем задержать (см. m119).
        from actions_pause import pending_actions_unless_paused
        actions = await pending_actions_unless_paused(
            db, channel_id, module_id, since_id, _BATCH_LIMIT)
        if actions:
            cursor = max(since_id, max(a["id"] for a in actions))
            return {"actions": actions, "cursor": cursor}
        if time.time() >= deadline:
            return {"actions": [], "cursor": since_id}
        if await request.is_disconnected():
            return {"actions": [], "cursor": since_id}
        await asyncio.sleep(_LONG_POLL_INTERVAL_SEC)


@router.post("/v1/module/{module_id}/ack", include_in_schema=False)
async def module_ack(module_id: str, request: Request):
    """Connector ACK'ает исполнение action.

    Body: {action_id: str, success: bool, error?: str}.

    Returns: {acked: bool}. False если ACK не изменил terminal result
    (повторный/поздний ACK, чужой канал или action не существует). Поздний ACK
    при этом сохраняется как receipt, но refund/status не переигрывает.
    """
    adapter = get_module(module_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "module_not_found", "module_id": module_id},
        )
    channel_id = await _verify_module_request(request, module_id)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "bad_json"},
        )
    action_id = str(body.get("action_id") or "")
    if not action_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "action_id_required"},
        )
    success_raw = body.get("success", True)
    if not isinstance(success_raw, bool):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "success_must_be_boolean"},
        )
    success = success_raw
    error_msg = str(body.get("error") or "")[:1000] if not success else None

    db = get_db()
    # A failed ACK for modules with action.failed must not become terminal before
    # the refund transaction succeeds.  We record the receipt and reserve this
    # live action, while the adapter atomically refunds + marks it failed below.
    # On adapter failure the row remains queued/dispatched, so an HTTP retry can
    # safely attempt the refund again.
    deferred_failure = (
        not success and adapter.manifest.supports_event("action.failed")
    )
    acked = await db.ack_action(
        channel_id=channel_id,
        module_id=module_id,
        action_id=action_id,
        success=success,
        error_msg=error_msg,
        transition=not deferred_failure,
    )

    # Manager's Technical Ready check is a zero-effect action travelling over
    # the same generic outbox as real game actions. Mirror its terminal ACK into
    # the Manager-owned diagnostic row; normal actions never match this prefix.
    if action_id.startswith("manager_"):
        async with db._connect() as conn:
            diagnostic_status = "acked" if success else "failed"
            await conn.execute(
                "UPDATE manager_diagnostic_actions "
                "SET status=?,completed_at=?,error=? "
                "WHERE channel_id=? AND module_id=? AND command_id=? "
                "AND status IN ('queued','delivered')",
                (diagnostic_status, time.time(), error_msg,
                 channel_id, module_id, action_id),
            )
            await conn.commit()

    # Sprint 5.29 audit fix #34: trace action lifecycle. Раньше ACK silent —
    # никаких логов; нельзя было сопоставить «buy_action enqueue» c «mod
    # processed». Теперь action_id трэйсится по обоим сторонам.
    import logging
    _log_ack = logging.getLogger("rimlink.module_api")
    if success and acked:
        _log_ack.info("[%s ACK ok] action_id=%s ch=%s",
                      module_id, action_id, channel_id)
    elif success:
        _log_ack.info(
            "[%s ACK receipt] action_id=%s ch=%s — "
            "terminal action, результат не изменён",
            module_id, action_id, channel_id)
    else:
        # 2026-06-14 audit (#21 closed): мод синхронно ACK'нул отказ → возвращаем
        # крустики. Прогоняем синтетический action.failed через тот же handle_event
        # → _on_action_failed (atomic refund, idempotent через REFUNDED: маркер),
        # поэтому реальный action.failed event позже НЕ даст двойного возврата.
        # Гейт по манифесту: только модули, объявившие action.failed.
        #
        # 2026-07-31 ВНЕШНИЙ АУДИТ (находка 1, КРИТИЧНО). Здесь не проверялся
        # результат `ack_action`. А он возвращает False, когда строка НЕ
        # перешла из queued/dispatched — то есть когда действие уже завершено.
        # Значит повторный `/ack` с `success=false` по уже выполненному
        # действию возвращал зрителю полную цену, ОСТАВЛЯЯ эффект в игре:
        # выполненное действие становилось бесплатным. Воспроизведено
        # аудитором через настоящий маршрут: acked=False, points +50,
        # строка ушла в `failed` с маркером возврата.
        #
        # Чиним асимметрично, и это важно. Поздний отказ мода (хендлер ACK'нул
        # true, а работу делает в главном потоке и падает позже) приходит НЕ
        # сюда, а отдельным событием `action.failed`
        # (`ActionFeedback.PostFailed` → `PostEventAsync`). Поэтому гейт
        # ставим только на маршрут `/ack`: он закрывает повтор, не ломая
        # законный асинхронный возврат.
        if not acked:
            _log_ack.warning(
                "[%s ACK FAIL] action_id=%s ch=%s — действие уже "
                "завершено, receipt записан, возврат НЕ выполняется",
                module_id, action_id, channel_id)
        elif deferred_failure:
            _log_ack.warning(
                "[%s ACK FAIL] action_id=%s ch=%s "
                "reason=%s — refunding",
                module_id, action_id, channel_id, error_msg)
            try:
                await adapter.handle_event(channel_id, ModuleEnvelope(
                    id=action_id, kind="event", type="action.failed", ts=0,
                    data={"action_id": action_id, "reason": error_msg or "ack_failed"},
                ))
            except Exception as _refund_exc:
                _log_ack.exception(
                    "[%s ACK refund] action_id=%s refund route failed: %s",
                    module_id, action_id, _refund_exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "status": "refund_retry_required",
                        "action_id": action_id,
                    },
                )

    return {"acked": acked, "action_id": action_id, "status": "acked" if success else "failed"}


# ── Этап 3 step 4: catalog read ──────────────────────────────────────────────

@router.get("/v1/module/{module_id}/catalog/{catalog_type}", include_in_schema=False)
async def module_catalog(module_id: str, catalog_type: str, request: Request):
    """Прочитать каталог для канала.

    Auth: либо Twitch JWT (зрительский фронт читает каталог стримера на котором
    он смотрит), либо session cookie (стример видит свой каталог в админке).

    Returns: {entries: [...]}.

    Каталог наполняется connector'ом через `module.catalog_update` event.
    Replace-семантика — последний catalog_update заместил всё, что было.
    """
    adapter = get_module(module_id)
    if not adapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "module_not_found", "module_id": module_id},
        )
    catalog_type = catalog_type.lower()
    if catalog_type not in adapter.manifest.catalogs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"status": "catalog_not_in_manifest",
                    "available": adapter.manifest.catalogs},
        )

    # Резолв channel_id: 1) JWT если есть → 2) session cookie 3) явный ?channel_id
    # Phase 1 — JWT viewer-frontend.
    from auth import verify_twitch_jwt
    jwt_result = verify_twitch_jwt(request)
    channel_id: int = 0
    if jwt_result.get("status") == "valid":
        try:
            channel_id = int(jwt_result.get("channel_id") or 0)
        except (TypeError, ValueError):
            channel_id = 0

    # Phase 2 — streamer dashboard (cookie session).
    if channel_id <= 0:
        from routes.streamer import _read_session_cookie
        ck = _read_session_cookie(request)
        if ck is not None:
            channel_id = int(ck)

    # Phase 3 — explicit query param. AUDIT 2026-05-29 (FULL_AUDIT fix #1):
    # раньше это давало UNAUTHENTICATED cross-tenant чтение каталога ЛЮБОГО
    # канала по ?channel_id= (enumerable). Теперь fallback разрешён ТОЛЬКО в
    # DEV_MODE (локальная диагностика). В prod без JWT/cookie → 401 ниже.
    if channel_id <= 0:
        from config import DEV_MODE
        if DEV_MODE:
            raw = request.query_params.get("channel_id")
            try:
                channel_id = int(raw) if raw else 0
            except ValueError:
                channel_id = 0

    if channel_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"status": "channel_id_unresolvable",
                    "message": "Provide JWT, session cookie, or ?channel_id="},
        )

    entries = await get_db().get_module_catalog(channel_id, module_id, catalog_type)
    return {"channel_id": channel_id, "module_id": module_id,
            "catalog_type": catalog_type, "entries": entries}

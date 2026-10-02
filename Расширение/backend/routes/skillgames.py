"""Authenticated private projections for the isolated viewer skill games."""
import json
import logging
import time
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from dependencies import get_db, require_jwt_user
from skillgames import config
from skillgames.service import GameError, SkillgameService

router = APIRouter()
logger = logging.getLogger('rimlink.skillgames.routes')
MAX_BODY_BYTES = 4096
RequestID = Annotated[str, Field(min_length=8,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')]
Cell = Annotated[StrictInt, Field(ge=0,le=35)]


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    request_id: RequestID


class Start(Command):
    game_type: Literal['minesweeper']
    mode: Literal['ranked','practice']
    difficulty: Literal['beginner','advanced']


class Action(Command):
    session_id: Annotated[str, Field(min_length=8,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')]
    version: Annotated[StrictInt, Field(ge=0,le=10000)]
    action: Literal['open','flag','unflag','quit','restart','place','autoplace','ready','fire']
    cell: Cell | None = None
    ships: Annotated[list[Annotated[list[Cell],Field(min_length=1,max_length=3)]],Field(min_length=4,max_length=4)] | None = None

    @model_validator(mode='after')
    def validate_action_payload(self):
        if self.action in ('open','flag','unflag','fire'):
            if self.cell is None or self.ships is not None:
                raise ValueError('cell required; ships forbidden')
        elif self.action=='place':
            if self.ships is None or self.cell is not None:
                raise ValueError('ships required; cell forbidden')
        elif self.cell is not None or self.ships is not None:
            raise ValueError('unexpected action data')
        return self


def get_service():
    db = get_db()
    if not hasattr(db,'_skillgame_service'):
        db._skillgame_service = SkillgameService(db)
    return db._skillgame_service


def _auth(request):
    # require_jwt_user checks both signed login and a positive registered channel.
    identity = require_jwt_user(request)
    if not identity:
        raise GameError('unauthorized',401,'Требуется авторизация Twitch и канал')
    return identity


async def _body(request, model):
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw)>MAX_BODY_BYTES:
            raise GameError('body_too_large',413)
    try:
        return model.model_validate_json(bytes(raw)).model_dump(exclude_none=True)
    except (ValidationError,ValueError):
        raise GameError('invalid_request',422,'Некорректные параметры запроса') from None


async def _dispatch(request, operation, model=None):
    payload, identity = None, None
    try:
        identity = _auth(request)
        user,cid = identity
        if model:
            payload = await _body(request,model)
        service = get_service()
        if operation=='config':
            return dict(success=True,catalog=config.catalog(),server_time=time.time(),poll_interval_ms=config.POLL_INTERVAL_MS,request_retention_seconds=config.REQUEST_RETENTION_SECONDS,
                        session_retention_seconds=config.SESSION_RETENTION_SECONDS,max_requests_per_user=config.MAX_RECEIPTS_PER_USER)
        if operation=='state':
            sid = request.query_params.get('session_id')
            if sid is not None and (not sid or len(sid)>64): raise GameError('invalid_request',422)
            return await service.state(cid,user,sid)
        if operation=='start':
            data,code = await service.start_game(cid,user,payload)
        elif operation=='action':
            data,code = await service.action(cid,user,payload)
        else:
            data,code = await service.queue(cid,user,payload,cancel=operation=='cancel')
        return JSONResponse(data,status_code=code)
    except HTTPException:
        raise  # Authentication/channel/rate errors retain status, detail and headers.
    except GameError as exc:
        return JSONResponse(dict(success=False,reason=exc.reason,message=exc.message),status_code=exc.status)
    except Exception:
        logger.exception('Skillgame operation failed: %s',operation)
        if operation=='action' and identity and payload:
            try:
                await get_service().void_for_service_failure(identity[1],identity[0],payload['session_id'])
            except Exception:
                # A DB outage leaves the original runtime lease stale. On recovery
                # it retires before requests can turn this into a timeout penalty.
                get_service().retire_runtime()
                logger.exception('Skillgame void deferred until storage recovers')
        return JSONResponse(dict(success=False,reason='service_unavailable',message='Сервис временно недоступен'),status_code=503)


@router.get('/api/skillgames/config')
async def skillgames_config(request: Request):
    return await _dispatch(request,'config')


@router.get('/api/skillgames/state')
async def skillgames_state(request: Request):
    return await _dispatch(request,'state')


@router.post('/api/skillgames/start')
async def skillgames_start(request: Request):
    return await _dispatch(request,'start',Start)


@router.post('/api/skillgames/action')
async def skillgames_action(request: Request):
    return await _dispatch(request,'action',Action)


@router.post('/api/skillgames/queue')
async def skillgames_queue(request: Request):
    return await _dispatch(request,'queue',Command)


@router.post('/api/skillgames/queue/cancel')
async def skillgames_queue_cancel(request: Request):
    return await _dispatch(request,'cancel',Command)

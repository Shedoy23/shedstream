"""
models.py — Pydantic-модели для всех роутеров.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, AliasChoices


# ===== ЗРИТЕЛИ =====

class UserAction(BaseModel):
    username: str
    channel_id: str

class ActivityRequest(BaseModel):
    username: str
    watch_time: int   # секунд просмотрено
    total_time: int = 0
    # Признаки того, что зритель ДЕЙСТВУЕТ, а не держит вкладку открытой.
    # Фронт слал их с самого первого коммита, а модель не объявляла — и
    # Pydantic молча выбрасывал. То есть данные для различения «смотрит» и
    # «ушёл» долетали до сервера и терялись (найдено 2026-08-23).
    active_clicks: int = 0
    mouse_moves: int = Field(default=0, validation_alias=AliasChoices("mouse_moves", "active_moves"))

class ChatMessageRequest(BaseModel):
    username: str
    message_length: int
    message_text: Optional[str] = None


# BetRequest + SpinSlotsRequest удалены 2026-05-10 (Phase 1.A casino removal)


# ===== ДУЭЛИ / ПЕРЕВОДЫ / БРАК =====

class DuelRequest(BaseModel):
    """Phase 1.F (2026-05-10): amount field удалён — дуэли только за ELO,
    без ставок крустиков (§6.2.6 wagering)."""
    creator: str
    target: str
    move: Literal["rock", "scissors", "paper"]

class AcceptDuelRequest(BaseModel):
    duel_id: str
    username: str
    move: Literal["rock", "scissors", "paper"]

# TransferRequest удалён 2026-05-10 (Phase 1.D compliance rework — P2P transfer)

class MarryRequest(BaseModel):
    user1: str
    user2: str

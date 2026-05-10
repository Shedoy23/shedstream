"""
models.py — Pydantic-модели для всех роутеров.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ===== ЗРИТЕЛИ =====

class UserAction(BaseModel):
    username: str
    channel_id: str

class ActivityRequest(BaseModel):
    username: str
    watch_time: int   # секунд просмотрено
    total_time: int = 0

class ChatMessageRequest(BaseModel):
    username: str
    message_length: int
    message_text: Optional[str] = None


# ===== КАЗИНО =====

class BetRequest(BaseModel):
    username: str
    amount: int = Field(..., gt=0)

class SpinSlotsRequest(BaseModel):
    username: str
    bet: int = Field(..., gt=0)


# ===== ДУЭЛИ / ПЕРЕВОДЫ / БРАК =====

class DuelRequest(BaseModel):
    creator: str
    target: str
    amount: int = Field(..., gt=0)
    move: Literal["rock", "scissors", "paper"]

class AcceptDuelRequest(BaseModel):
    duel_id: str
    username: str
    move: Literal["rock", "scissors", "paper"]

# TransferRequest удалён 2026-05-10 (Phase 1.D compliance rework — P2P transfer)

class MarryRequest(BaseModel):
    user1: str
    user2: str

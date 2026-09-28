"""
modules/_base.py — ModuleAdapter ABC + типы Module API.

Контракт между ядром платформы и pluggable модулями интеграции с играми.
Соответствует docs/MODULE_API.md §6 (lifecycle), §7 (events), §8 (actions).

Модуль (концептуально):
    [game-side connector в моде/плагине]
        ↓ HTTP/WS
    [backend module adapter — этот файл реализует core-side]
        ↓ Python calls
    [core: db, bot, EventManager, и пр.]

Текущая реализация — REST long-polling per §3.1 спеки. WS/SSE — future.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Manifest — параллель `manifest.yaml` модуля в Python-структуре. Загружается
# `_loader.load_manifest()` из YAML-файла модуля.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ModuleManifest:
    id: str                                    # уникальный slug, [a-z0-9_]
    version: str                               # semver — версия самого модуля
    core_api_version: str                      # с какими версиями core API совместим
    display_name: str
    description: str = ""
    icon: Optional[str] = None
    events: List[str] = field(default_factory=list)               # core-events которые модуль может слать
    actions: List[str] = field(default_factory=list)              # core-actions которые модуль исполняет
    extension_events: List[str] = field(default_factory=list)     # custom events вне core API
    extension_actions: List[str] = field(default_factory=list)    # custom actions вне core API
    catalogs: List[str] = field(default_factory=list)             # shop / events / etc
    ui_slots: List[str] = field(default_factory=list)             # frontend slots модуль занимает

    def supports_action(self, action_type: str) -> bool:
        """Может ли модуль исполнить action данного типа.
        Используется core'ом перед попыткой dispatch — защита от
        рассинхрона версий (см. §5 спеки)."""
        return action_type in self.actions or action_type in self.extension_actions

    def supports_event(self, event_type: str) -> bool:
        """Является ли event декларированным в manifest'е модуля."""
        return event_type in self.events or event_type in self.extension_events


# ─────────────────────────────────────────────────────────────────────────────
# Wire-уровень envelope — §3.4 спеки. Все события/actions ходят в этом конверте.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ModuleEnvelope:
    id: str            # unique message id — для ACK
    kind: str          # "event" | "action" | "ack" | "ping"
    type: str          # типа `player.linked` или `player.spawn`
    ts: int            # epoch ms на стороне отправителя
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def user(self):
        """2026-06-05 — ModuleEnvelope сам поле user не несёт; код в _adapter
        звал env.user → AttributeError (падали settlements_catalog + caravan
        handlers при отсутствии owner). Берём user-идентификатор из payload."""
        return self.data.get("user") or self.data.get("owner") or self.data.get("username")


# ─────────────────────────────────────────────────────────────────────────────
# ModuleAdapter — то что core держит в памяти про каждый загруженный модуль.
# Конкретные модули наследуются и реализуют abstract'ные методы.
#
# В отличие от connector'а (тот живёт в моде/игре и шлёт события через сеть),
# adapter живёт в нашем backend'е — он переводит сетевые события в core-вызовы
# и наоборот.
# ─────────────────────────────────────────────────────────────────────────────
class ModuleAdapter(ABC):
    """Базовый класс для in-process модуля платформы.

    Подкласс должен:
      1. Загрузить свой manifest (обычно через `_loader`)
      2. Реализовать `handle_event` (как core реагирует на event от connector'а)
      3. Реализовать `dispatch_action` (как core отправляет action в connector)
      4. Опционально override'нуть lifecycle hooks (on_session_start, и т.д.)

    Пример:
        class RimWorldAdapter(ModuleAdapter):
            async def handle_event(self, channel_id, env): ...
            async def dispatch_action(self, channel_id, env): ...
    """

    def __init__(self, manifest: ModuleManifest):
        self.manifest = manifest
        # Per-channel state: какие channel_id'ы сейчас активны (есть session_start
        # без session_end). Заполняется в on_session_start/_end. Используется
        # core'ом чтобы не слать actions в каналы где нет коннектора.
        self._active_channels: set = set()

    @property
    def id(self) -> str:
        return self.manifest.id

    # ── Lifecycle (§6) ──────────────────────────────────────────────────────

    async def on_hello(self, channel_id: int, connector_version: str,
                        manifest_digest: str) -> Dict[str, Any]:
        """Connector прислал module.hello. Возвращаем module.welcome payload.
        По умолчанию: подтверждаем capabilities из manifest'а."""
        return {
            "core_version": "1.0.0",  # TODO read from version.py
            "accepted_capabilities": {
                "events": self.manifest.events + self.manifest.extension_events,
                "actions": self.manifest.actions + self.manifest.extension_actions,
            },
            "module_id": self.id,
            "manifest_version": self.manifest.version,
        }

    async def on_session_start(self, channel_id: int, data: Dict[str, Any]) -> None:
        """module.session_start — connector активировался. Вызывает session-scoped
        cleanup каталогов (см. MULTITENANT_PLAN.md §H)."""
        self._active_channels.add(int(channel_id))

    async def on_session_end(self, channel_id: int, data: Dict[str, Any]) -> None:
        """module.session_end — connector корректно отключился."""
        self._active_channels.discard(int(channel_id))

    def is_active(self, channel_id: int) -> bool:
        """Есть ли активный коннектор для канала. Используется core'ом перед
        dispatch_action — нет смысла слать action если connector offline."""
        return int(channel_id) in self._active_channels

    # ── Required overrides ──────────────────────────────────────────────────

    @abstractmethod
    async def handle_event(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Обрабатываем event от connector'а. Может быть стандартным (player.linked,
        player.died, ...) или extension (для RimWorld — pawn.gene_changed).

        ВАЖНО: метод вызывается core'ом ПОСЛЕ того как event прошёл валидацию
        (manifest declared, JSON-schema). Нагрузка adapter'а — переводить
        в core-вызовы (db, bot, EventManager). Не плодить network/IO без
        необходимости.
        """

    @abstractmethod
    async def dispatch_action(self, channel_id: int, env: ModuleEnvelope) -> Dict[str, Any]:
        """Отправляем action в connector. Возвращаем preliminary-ack ({queued: True}).
        Реальный ACK прилетит обратно от connector'а через on_event с kind=ack.

        В REST long-poll реализации (§3.1 transport): action кладётся в outbox
        очередь канала, connector забирает по GET /v1/module/<id>/actions.
        В WS реализации (future): отправляется напрямую в открытый сокет.
        """


__all__ = [
    "ModuleManifest",
    "ModuleEnvelope",
    "ModuleAdapter",
]


# ── Возврат по просрочке: только пока игра не забрала заявку ─────────────────
# Причина, с которой сторож просроченных `queued` (main._expire_stale_queued)
# зовёт штатный обработчик возврата модуля.
TTL_EXPIRED_REASON = "queued_ttl_expired"


async def refund_still_due(conn, module_id: str, channel_id: int,
                           action_id: str, reason: str) -> bool:
    """Уместен ли ещё возврат — вызывать ВНУТРИ транзакции возврата.

    Сторож выбирает просроченные `queued` одной транзакцией, а деньги
    возвращает другой, через обработчик модуля. Между ними игра может забрать
    заявку и выполнить её: без этой проверки зритель получал эффект И деньги
    назад, а успешная заявка записывалась ошибочной (внешний обзор
    2026-09-11, tests/test_module_action_races.py [1]).

    Для прочих причин отказа всегда True: их присылает мод по заявке, которую
    уже взял, — статус там `dispatched`, и это нормально.

    Срок заново не проверяется намеренно: `module_actions.created_at` после
    вставки не меняет никто, значит заявка, просроченная при выборке,
    просрочена и сейчас. Решает только статус.
    """
    if reason != TTL_EXPIRED_REASON:
        return True
    cur = await conn.execute(
        "SELECT status FROM module_actions "
        "WHERE channel_id=? AND module_id=? AND action_id=?",
        (int(channel_id), module_id, action_id))
    row = await cur.fetchone()
    return bool(row) and row[0] == "queued"

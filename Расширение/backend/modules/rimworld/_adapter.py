"""
modules/rimworld/_adapter.py — RimWorldAdapter (ModuleAdapter implementation).

Stub-уровень для этапа 3 step 1. handle_event/dispatch_action возвращают
безопасные no-op'ы — реальная логика придёт в шагах миграции по
docs/MODULE_MIGRATION.md.

Полные реализации event-обработчиков пока живут в `backend/rimworld.py`
(~1981 строка) и вызываются напрямую из routes. Этот adapter — точка
входа для будущего, когда ядро будет dispatch'ить через Module API
вместо прямых импортов rimworld.py.
"""
from __future__ import annotations

from typing import Any, Dict

from .._base import ModuleAdapter, ModuleEnvelope


class RimWorldAdapter(ModuleAdapter):
    """RimWorld-specific module adapter.

    Шаг 1 (текущий): stub для регистрации в реестре и handshake.
    Шаги миграции — см. docs/MODULE_MIGRATION.md.
    """

    async def handle_event(self, channel_id: int, env: ModuleEnvelope) -> None:
        """Stub. До миграции мод присылает события через `/api/rimworld/*`
        напрямую (legacy path), не через Module API envelope. Когда мод
        начнёт слать через `POST /v1/module/rimworld/events` — этот метод
        наполнится диспетчером по env.type."""
        pass

    async def dispatch_action(self, channel_id: int, env: ModuleEnvelope) -> Dict[str, Any]:
        """Stub. До миграции actions исполняются прямыми /api/rimworld/<verb>
        вызовами, не через action queue. Когда мод начнёт poll'ить
        `GET /v1/module/rimworld/actions` — этот метод заведует outbox-ом."""
        return {"queued": False, "reason": "not_implemented_yet", "action_id": env.id}

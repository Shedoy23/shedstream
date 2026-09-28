# -*- coding: utf-8 -*-
"""_mod_queue.py — ЕДИНСТВЕННОЕ место, где действие попадает в очередь мода.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ (2026-07-28, дефекты PB-01 / PB-03).

Общая касса (`routes/bannerlord.py`) кладёт действие в `module_actions`
правильно: с ценой в payload и с `client_action_id`. Но действия из
`_BACKEND_ONLY_ACTIONS` общий enqueue ПРОПУСКАЮТ — их обработчики (мастерские,
караваны, приказы отряду, дипломатия, вассалы, семья) вставляли строку сами,
собирая payload с нуля. И теряли оба кассовых поля:

* **`price`** → `_on_action_failed` читает `int(parsed.get("price") or 0)`,
  получает 0, пишет `REFUNDED:0 (no_price)` и НЕ ВОЗВРАЩАЕТ ДЕНЕГ.
  На проде 2026-07-28 таких случаев 74: приказ отряду ×63 (500💎),
  мастерская ×5 (2500💎), караван ×5 (4000💎), мир ×1 (2000💎).
* **`client_action_id`** → защита от повторного нажатия ищет строку по этому
  ключу и не находит: у всех спец-действий он `NULL`.

Чинить правкой каждого места нельзя — их тринадцать, и четырнадцатое заведёт
ту же дыру. Поэтому один вход, и он сам переносит кассовые поля.

Модуль намеренно НИ ОТ ЧЕГО не зависит внутри проекта: `routes/bannerlord.py`
импортирует обработчики лениво, обработчики импортируют этот файл — цикла не
возникает ни при каком порядке загрузки.
"""
from __future__ import annotations

import json as _json
from typing import Any, Dict, Optional


async def enqueue_mod_action(
    conn,
    channel_id: int,
    action_id: str,
    action_type: str,
    payload: Dict[str, Any],
    src: Optional[Dict[str, Any]] = None,
    module_id: str = "bannerlord",
) -> None:
    """Положить действие в очередь мода, перенеся кассовые поля из `src`.

    `src` — тело запроса зрителя (`data`), каким его получил обработчик. Из
    него берутся:
      * `price` — фактически списанная сумма. Её проставляет касса ПЕРЕД
        вызовом спец-обработчика (`routes/bannerlord.py`), поэтому здесь она
        уже правильная, с учётом ролевых скидок;
      * `client_action_id` — ключ идемпотентности от фронта.

    Если `src` не передан, действие считается служебным/бесплатным: цена 0,
    ключа нет. Это осознанный дефолт для внутренних enqueue, где кассы не было.

    Транзакцией управляет ВЫЗЫВАЮЩИЙ: здесь нет ни BEGIN, ни commit — вставка
    обязана лежать в той же транзакции, что и списание, иначе вернётся класс
    «деньги списаны, действие не поставлено».
    """
    src = src or {}
    data = dict(payload)

    # Цену пишем всегда — даже нулевую. Отсутствие поля и честный ноль это
    # РАЗНЫЕ вещи: по отсутствию невозможно отличить бесплатное действие от
    # потерянной цены, и ровно на этом три месяца не замечали PB-01.
    try:
        data["price"] = int(src.get("price") or 0)
    except (TypeError, ValueError):
        data["price"] = 0

    client_action_id = (str(src.get("client_action_id") or "")).strip() or None

    await conn.execute(
        "INSERT INTO module_actions "
        "(channel_id, module_id, action_id, type, data, status, client_action_id) "
        "VALUES (?, ?, ?, ?, ?, 'queued', ?)",
        (channel_id, module_id, action_id, action_type,
         _json.dumps(data, ensure_ascii=False), client_action_id),
    )

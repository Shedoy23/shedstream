# -*- coding: utf-8 -*-
"""refusals.py — причина отказа мода ShedColony → текст зрителю.

ЗАЧЕМ. До 2026-09-05 мод отвечал одним словом `op_failed` на любой отказ:
«в колонии нет таверны» и «мод сломан» выглядели одинаково. По базе нельзя было
отличить законный отказ от мёртвой механики — `colony.spawn_visitor` отказал
13 раз подряд, и триаж записал его в сломанные, хотя таверны просто не было.
Теперь мод шлёт `op_failed: <причина>`, а этот словарь превращает причину в
человеческий текст, который уходит зрителю в уведомление вместе с возвратом.

ПОЧЕМУ СЛОВАРЬ ЗДЕСЬ, А НЕ ВО ФРОНТЕ — та же причина, что у Bannerlord
(`modules/bannerlord/refusals.py`): фронт замерзает на CDN Twitch до следующего
ревью, бэкенд деплоится за минуты, а причины появляются вместе с действиями.

Незнакомую причину НЕ прячем: показываем как есть. Молчание хуже английской
фразы — зритель хотя бы поймёт, что отказ осмысленный, а мы увидим, что
дописать в словарь.
"""

# Коды, которые ShedActions возвращает сам (без обращения к колонии).
_CODES = {
    "no_colony": "Колония стримера сейчас недоступна — возможно, он не в игре.",
    "no_citizen": "Твой колонист не найден в колонии.",
    "no_name": "Не указано имя колониста.",
    "no_level": "У колонии не хватает уровня для этого.",
    "no_job": "Работа не выбрана.",
    "bad_job": "Такой работы в колонии нет.",
    "bad_amount": "Некорректное количество.",
    "unknown_skill": "Такого навыка нет.",
    "spawn_failed": "Колониста не удалось поселить — в колонии нет свободного места.",
    "unknown_action": "Мод стримера не знает такого действия — он старой версии.",
    "op_failed": "Действие не выполнилось в игре.",
}

# Точные фразы ColonyOps.Result.fail(...).
_EXACT = {
    "no tavern in the colony":
        "В колонии нет таверны — гостю некуда прийти.",
    "the tavern can't take a visitor right now":
        "Таверна сейчас не может принять гостя — там уже некуда селить.",
    "no raid right now — spies only help during a raid":
        "Сейчас нет рейда — шпионы полезны только во время нападения.",
    "spies are already active for this raid":
        "Шпионы уже работают в этом рейде.",
    "no warehouse in the colony": "В колонии нет склада.",
    "warehouse isn't loaded": "Склад ещё не прогружен — попробуй чуть позже.",
    "warehouse is full — couldn't store the donation":
        "Склад забит — припасы некуда положить.",
    "warehouse has no min-stock module": "У склада нет модуля минимальных запасов.",
    "warehouse min-stock full — upgrade the warehouse to add more item rules":
        "Список минимальных запасов заполнен — складу нужен апгрейд.",
    "all houses are full of other viewers' colonists":
        "Все дома заняты колонистами других зрителей.",
    "building isn't built yet": "Здание ещё не построено.",
    "already at max level": "Здание уже максимального уровня.",
    "an upgrade/build is already in progress here": "Здесь уже идёт стройка.",
    "couldn't start the upgrade (needs a builder in range, or it's research-locked)":
        "Апгрейд не начался: нужен строитель рядом или ещё не открыто исследование.",
    "streamer is offline — the builder can't work without them online":
        "Стример сейчас не в игре — строитель без него не работает.",
    "no built University in the colony": "В колонии нет построенного университета.",
    "research already complete": "Это исследование уже завершено.",
    "research already in progress": "Это исследование уже идёт.",
    "research is not in progress": "Это исследование сейчас не идёт.",
    "couldn't complete the research": "Исследование не удалось завершить.",
    "prerequisites not met (parent research / university level / branch cap)":
        "Не выполнены условия: нужно предыдущее исследование или уровень университета.",
    "no quests are loaded": "Квесты ещё не загрузились.",
    "all quests already unlocked": "Все квесты уже открыты.",
    "no item": "Предмет не выбран.",
    "empty name": "Пустое имя.",
}

# Причины, которые мод достраивает конкретикой: сверяем по началу строки.
_PREFIX = (
    ("unknown item ", "Такого предмета в игре нет."),
    ("can't resolve an item for: ", "Для этого действия не нашлось подходящего предмета."),
    ("no building at ", "По этим координатам здания нет."),
    ("bad position '", "Неверные координаты здания."),
    ("couldn't hire ", "Нанять не получилось."),
    ("couldn't house ", "Поселить не получилось — нет свободного дома."),
    ("that request is no longer open (id ", "Эта просьба уже закрыта — кто-то успел раньше."),
    ("guard task is already '", "У стражника уже стоит эта задача."),
    ("retreat is already ", "Такой режим отступления уже включён."),
    ("unknown guard task ", "Такой задачи у стражников нет."),
    ("unknown armour tier ", "Такого тира брони нет."),
    ("unknown research ", "Такого исследования нет."),
    ("all ", "Улучшать уже нечего — всё на максимуме."),
)

_FALLBACK = "Действие не выполнилось в игре."


def describe(reason: str) -> str:
    """Причина от мода → фраза зрителю. Всегда возвращает непустой текст."""
    raw = (reason or "").strip()
    if not raw:
        return _FALLBACK

    detail = raw
    if raw.startswith("op_failed:"):
        detail = raw[len("op_failed:"):].strip()
    elif raw in _CODES:
        return _CODES[raw]

    if not detail:
        return _CODES["op_failed"]
    if detail in _CODES:
        return _CODES[detail]
    if detail in _EXACT:
        return _EXACT[detail]
    for prefix, text in _PREFIX:
        if detail.startswith(prefix):
            return text
    # Незнакомая причина — показываем как есть, это честнее молчания.
    return f"Действие не выполнилось: {detail}"

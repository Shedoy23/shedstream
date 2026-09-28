# -*- coding: utf-8 -*-
"""Зритель платит ровно ту сумму, которую увидел на кнопке.

ЗАЧЕМ. У черт и генов цена прогрессивная: `base × (куплено + 1)`. Панель берёт
её из каталога в момент отрисовки, сервер считает свою в момент списания.
Между этими моментами счётчик мог вырасти — покупка из другой вкладки,
оставленная открытой панель — и зритель, нажав «купить за 3000», платил 6000.
Отказа не было: сервер молча списывал свою цену.

Само по себе «цена приходит с сервера» этого не закрывает: сервер отдаёт
ПРАВИЛЬНУЮ цену на момент отрисовки, а списывает правильную на момент
нажатия — и обе правильные.

Проверяем поведение исполнением `_price_consent_error`, а не наличием строк:
дыра была в ОТСУТСТВИИ проверки, а отсутствие грепом не отличить от «ещё не
написали» (урок 09.09, `LESSONS.md`).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Расширение" / "backend"))
for _var, _val in (("TWITCH_OAUTH_TOKEN", "oauth:x"), ("TWITCH_CLIENT_ID", "x"),
                   ("TWITCH_CLIENT_SECRET", "x"), ("TWITCH_BOT_ID", "x"),
                   ("TWITCH_CHANNEL_NAME", "x")):
    os.environ.setdefault(_var, _val)

import rimworld  # noqa: E402

fails: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("  OK   " if ok else "  FAIL ") + name)
    if not ok:
        fails.append(name)


consent = rimworld._price_consent_error

# [1] Цена на экране совпала с серверной — покупка идёт.
check("совпавшая цена не мешает покупке",
      consent({"expected_price": 3000}, 3000, "ген", 3) is None)

# [2] Цена выросла между отрисовкой и нажатием — ОТКАЗ, ничего не списано.
err = consent({"expected_price": 3000}, 6000, "ген", 6)
ok = bool(err) and err.get("success") is False
if ok:
    msg = err.get("message", "")
    ok = "3000" in msg and "6000" in msg and "не списано" in msg
if not ok:
    print("     ожидался отказ, называющий обе суммы; получено: %r" % (err,))
check("подорожание между показом и нажатием даёт отказ с обеими суммами", ok)

# [3] Цена УПАЛА — тоже отказ: зритель должен увидеть новую сумму, а не
#     получить сюрприз в другую сторону. Молчаливое списание меньшего —
#     всё равно списание не той суммы, на которую нажимали.
check("подешевение тоже останавливает покупку",
      (consent({"expected_price": 6000}, 3000, "черта", 3) or {}).get("success") is False)

# [4] Поле не прислано — проверки нет. Публичная сборка 0.0.1 на CDN его не
#     шлёт, и ломать ей покупки нельзя.
check("без expected_price поведение прежнее (старый CDN-клиент жив)",
      consent({}, 6000, "ген", 6) is None and
      consent({"expected_price": None}, 6000, "ген", 6) is None and
      consent({"expected_price": ""}, 6000, "ген", 6) is None)

# [5] Мусор вместо числа — отказ, а не падение и не пропуск проверки.
check("нечисловая expected_price отклоняется",
      (consent({"expected_price": "бесплатно"}, 3000, "ген", 3) or {}).get("success") is False)

# [6] Строковое число от JSON-клиента считается нормально.
check("строковое число сверяется как число",
      consent({"expected_price": "3000"}, 3000, "ген", 3) is None)

# [7] Главное, чего проверка НЕ должна делать: expected_price не имеет права
#     стать суммой списания. Функция обязана лишь возвращать отказ или None —
#     ровно та дыра, которую 09.09 закрывали в Bannerlord (клиентское поле,
#     доехавшее до исполнения).
res = consent({"expected_price": 1}, 50_000, "ген", 50)
check("expected_price не подменяет цену, а только останавливает покупку",
      isinstance(res, dict) and set(res) == {"success", "message"})

# ── Проверка ВЫЗОВА, а не только функции ─────────────────────────────────────
# Тесты выше доказывают поведение самой сверки. Они останутся зелёными, если
# кто-то уберёт её ВЫЗОВ из обработчика покупки — а это ровно та форма дефекта,
# на которой мы уже обожглись (гейт лимита детей был зелёным при живой дыре).
# Здесь проверка СТРУКТУРНАЯ, по разбору синтаксиса: она видит, что вызов есть
# в теле нужной функции и стоит РАНЬШЕ проверки баланса. Это слабее исполнения
# и так и называется — но сильнее поиска строки: переименование, перенос в
# другую функцию или удаление вызова она замечает.
import ast  # noqa: E402

_src = (ROOT / "Расширение" / "backend" / "rimworld.py").read_text(encoding="utf-8")
_tree = ast.parse(_src)
_funcs = {n.name: n for n in ast.walk(_tree)
          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _consent_precedes_balance(fn_name: str) -> bool:
    fn = _funcs.get(fn_name)
    if fn is None:
        print("     функция %s не найдена — обработчик переименовали?" % fn_name)
        return False
    consent_line = balance_line = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "_price_consent_error":
            consent_line = node.lineno if consent_line is None else min(consent_line, node.lineno)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get_points":
            balance_line = node.lineno if balance_line is None else min(balance_line, node.lineno)
    if consent_line is None:
        print("     в %s нет вызова _price_consent_error — сверка отключена" % fn_name)
        return False
    if balance_line is not None and consent_line > balance_line:
        print("     в %s сверка стоит ПОСЛЕ проверки баланса (%d > %d)"
              % (fn_name, consent_line, balance_line))
        return False
    return True


for _handler in ("buy_gene", "buy_trait"):
    check("сверка цены вызвана в %s до проверки баланса" % _handler,
          _consent_precedes_balance(_handler))

if fails:
    print("\nПРОВАЛЕНО: " + "; ".join(fails))
    raise SystemExit(1)
print("\nВСЁ ЗЕЛЁНОЕ")

# -*- coding: utf-8 -*-
"""Дашборд стримера отрисовывается и не пропускает чужой скрипт.

Раньше страница была f-string на 616 строк с 374 удвоенными скобками: каждое
правило CSS и каждый кусок JS писались как `{{`/`}}`, одна забытая скобка роняла
дашборд в 500 уже на проде, и проверить файл заранее не мог ни один инструмент.
2026-07-26 разметка вынесена в `templates/streamer_dashboard.html`.

Тест держит два свойства, которые легко потерять при правках внешнего вида:
  1. страница вообще собирается — раньше это проверялось только на проде;
  2. имя канала экранируется. Оно приходит из профиля Twitch, то есть его
     задаёт посторонний человек. Автоэкранирование Jinja здесь намеренно
     выключено (иначе экранировали бы дважды), поэтому свойство держится
     вызывающим кодом — и обязано проверяться.

Запуск:  python tests/test_dashboard_render.py
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.chdir(pathlib.Path(__file__).resolve().parent.parent)

for _k, _v in (("TWITCH_OAUTH_TOKEN", "x"), ("TWITCH_CLIENT_ID", "x"),
               ("TWITCH_CLIENT_SECRET", "x"), ("TWITCH_BOT_ID", "x"),
               ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(_k, _v)

passed = 0
failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print("  OK   %s" % msg)
    else:
        failed += 1
        print("  FAIL %s" % msg)


def main():
    import routes.streamer as st

    NORMAL = {"login": "shedoy23", "display_name": "Shedoy23",
              "channel_id": 98319857, "tier": "free",
              "active_module": "bannerlord", "registered_at": "2026-06-01",
              "oauth_access_token": "tok"}

    html_out = st._dashboard_html(NORMAL)
    check(html_out.lstrip().startswith("<!DOCTYPE html>"),
          "страница собирается и начинается с DOCTYPE")
    check(len(html_out) > 20000,
          "страница целая, а не обрезанная (%d символов)" % len(html_out))
    check("Shedoy23" in html_out and "98319857" in html_out,
          "данные канала подставились")
    check("{{" not in html_out and "}}" not in html_out,
          "в выдаче не осталось неподставленных меток шаблона")

    # Пустая запись не должна ронять страницу: канал может быть без части полей.
    try:
        empty = st._dashboard_html({})
        ok_empty = empty.lstrip().startswith("<!DOCTYPE html>")
    except Exception as e:
        ok_empty = False
        print("     упало: %s: %s" % (type(e).__name__, e))
    check(ok_empty, "пустая запись канала не роняет страницу")

    # ── Главное: чужой скрипт в имени ──────────────────────────────────────
    EVIL = dict(NORMAL)
    EVIL["display_name"] = '<script>alert(1)</script>'
    EVIL["active_module"] = '</script><img src=x onerror=alert(2)>'
    evil_out = st._dashboard_html(EVIL)

    check("<script>alert(1)</script>" not in evil_out,
          "скрипт из ИМЕНИ канала не попал в страницу как код")
    check("&lt;script&gt;" in evil_out,
          "он попал туда экранированным, то есть виден как текст")
    # Название модуля попадает в ДВА контекста, и «опасно» в них значит разное.
    # Первая версия этой проверки искала подстроку по всей странице и краснела
    # зря: внутри JS-строки `<img ...>` — безобидный текст, браузер его не
    # исполнит. Проверять надо по месту, а не по факту наличия символов.
    import re as _re
    without_js = _re.sub(r"<script\b.*?</script>", "", evil_out, flags=_re.S)
    check("<img" not in without_js,
          "в HTML-контексте картинки-ловушки нет — только экранированный текст")
    check("&lt;img" in evil_out,
          "она отрисована как ТЕКСТ, а не как тег")
    check("<\\/script>" in evil_out,
          "закрывающий тег внутри JS-строки экранирован — скрипт не разрывается")

    # Шаблон лежит там, где его можно открыть и править как обычный HTML.
    tpl = pathlib.Path("templates/streamer_dashboard.html")
    check(tpl.exists() and tpl.stat().st_size > 20000,
          "шаблон лежит отдельным файлом (%s)" % tpl)

    print("=" * 70)
    print("PASSED: %d   FAILED: %d" % (passed, failed))
    print("ALL GREEN — дашборд собирается, чужой скрипт не проходит."
          if not failed else "КРАСНО — дашборд сломан или пропускает скрипт.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

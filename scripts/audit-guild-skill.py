# -*- coding: utf-8 -*-
"""Аудит работы A6 — прокачка навыка гильдии (реестр 0.0.2, трек A).

Механика ни разу не использована на проде (guild_skills = 0 строк), поэтому
данными её проверить нельзя — только прогоном. Гоняется на ОТДЕЛЬНОЙ копии
локальной базы: прод и локальная копия не затрагиваются.

Что доказываем: казна и уровень меняются одной операцией, недостаток казны и
чужая роль не двигают ни то, ни другое, потолок уровня держит, а два
одновременных запроса дают ровно одно списание.

ЗАПУСК (сначала развернуть копию: `python scripts/local-setup.py`):

    python scripts/audit-guild-skill.py

Прод не трогает: работает на копии копии, в %USERPROFILE%\\shedstream-local\\.
Другую базу можно подсунуть через переменную AUDIT_DB.
"""
import asyncio
import os
import shutil
import sqlite3
import sys

HOME = os.environ.get("USERPROFILE", os.path.expanduser("~"))
LOCAL = os.path.join(HOME, "shedstream-local")
# База — копия прода, развёрнутая `python scripts/local-setup.py`.
SRC = os.environ.get("AUDIT_DB", os.path.join(LOCAL, "viewers.db"))
# Рабочая копия кладётся РЯДОМ С НЕЙ, вне репозитория: 2026-06-25 локальная
# база рядом с кодом уехала в архив деплоя и затёрла боевую.
WORK = os.path.join(LOCAL, "a6_work.db")

fails = []


def check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    if not cond:
        fails.append(name)
    print(f"  [{mark}] {name}" + (f"  — {detail}" if detail else ""))


def snap(path, guild_id, skill="extra_member_slots"):
    c = sqlite3.connect(path)
    bal = c.execute("SELECT balance FROM guilds WHERE id=?", (guild_id,)).fetchone()[0]
    row = c.execute(
        "SELECT level FROM guild_skills WHERE guild_id=? AND skill_key=?", (guild_id, skill)
    ).fetchone()
    c.close()
    return bal, (row[0] if row else 0)


async def main():
    # Старые -wal/-shm ОБЯЗАТЕЛЬНО снести до копирования: если их не удалить,
    # sqlite применит журнал прошлого прогона поверх свежей копии, и тест
    # увидит чужое состояние. Ровно на это я и наступил: второй прогон
    # стартовал с уже прокачанным до потолка навыком.
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(WORK + suffix):
            os.remove(WORK + suffix)
    shutil.copy(SRC, WORK)
    for suffix in ("-wal", "-shm"):
        if os.path.exists(SRC + suffix):
            shutil.copy(SRC + suffix, WORK + suffix)

    # Каталог расширения назван по-русски — ищем backend программно, а не по
    # захардкоженному имени.
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backend = next(
        (os.path.join(repo, d, "backend") for d in os.listdir(repo)
         if os.path.isdir(os.path.join(repo, d, "backend"))),
        None,
    )
    if not backend:
        print("не нашёл каталог backend — запускать из репозитория")
        return 2
    os.chdir(backend)
    sys.path.insert(0, backend)
    from database import Database
    from config import GUILD_SKILLS_CONFIG

    db = Database(WORK)
    GUILD, CH, MASTER, MEMBER = 1, 98319857, "shedoy23", "stepuhatgn"
    SKILL = "extra_member_slots"
    costs = GUILD_SKILLS_CONFIG[SKILL]["cost_per_level"]
    maxlvl = GUILD_SKILLS_CONFIG[SKILL]["max_level"]

    print(f"навык {SKILL}: max_level={maxlvl}, цены по уровням={costs}\n")

    # ── 1. Казны не хватает ─────────────────────────────────────────────────
    print("1. Казны не хватает (1337 < %d)" % costs[0])
    b0, l0 = snap(WORK, GUILD)
    r = await db.upgrade_guild_skill(MASTER, SKILL, channel_id=CH)
    b1, l1 = snap(WORK, GUILD)
    check("отказ по причине insufficient_guild_balance", r.get("reason") == "insufficient_guild_balance", str(r))
    check("казна не тронута", b0 == b1, f"{b0} -> {b1}")
    check("уровень не вырос", l0 == l1 == 0, f"{l0} -> {l1}")

    # ── 2. Не мастер ────────────────────────────────────────────────────────
    print("\n2. Прокачку жмёт обычный участник, не мастер")
    c = sqlite3.connect(WORK)
    # Казна должна покрыть ВСЕ уровни: 50k+100k+200k+400k+800k = 1.55M.
    # В первой версии теста тут стоял 1M — прокачка честно отказала на пятом
    # уровне, и это был дефект теста, а не механики.
    c.execute("UPDATE guilds SET balance=? WHERE id=?", (2_000_000, GUILD))
    c.commit()
    c.close()
    b0, l0 = snap(WORK, GUILD)
    r = await db.upgrade_guild_skill(MEMBER, SKILL, channel_id=CH)
    b1, l1 = snap(WORK, GUILD)
    check("отказ по причине not_master", r.get("reason") == "not_master", str(r))
    check("казна не тронута", b0 == b1, f"{b0} -> {b1}")
    check("уровень не вырос", l0 == l1, f"{l0} -> {l1}")

    # ── 3. Законная прокачка по всем уровням ────────────────────────────────
    print("\n3. Мастер прокачивает навык до потолка")
    for lvl in range(maxlvl):
        b0, l0 = snap(WORK, GUILD)
        r = await db.upgrade_guild_skill(MASTER, SKILL, channel_id=CH)
        b1, l1 = snap(WORK, GUILD)
        want_cost = costs[lvl]
        check(f"уровень {lvl} -> {lvl+1}", r.get("upgraded") is True and l1 == lvl + 1, str(r))
        check(f"  списано ровно {want_cost}", b0 - b1 == want_cost, f"{b0} -> {b1} (разница {b0-b1})")
        check("  new_balance в ответе совпадает с базой", r.get("new_balance") == b1,
              f"ответ={r.get('new_balance')} база={b1}")

    # ── 4. Потолок ──────────────────────────────────────────────────────────
    print("\n4. Попытка перешагнуть потолок")
    b0, l0 = snap(WORK, GUILD)
    r = await db.upgrade_guild_skill(MASTER, SKILL, channel_id=CH)
    b1, l1 = snap(WORK, GUILD)
    check("отказ по причине max_level", r.get("reason") == "max_level", str(r))
    check("казна не тронута", b0 == b1, f"{b0} -> {b1}")
    check("уровень остался на потолке", l1 == maxlvl, f"{l1}")

    # ── 5. Неизвестный навык ────────────────────────────────────────────────
    print("\n5. Неизвестный навык")
    b0, _ = snap(WORK, GUILD)
    r = await db.upgrade_guild_skill(MASTER, "no_such_skill", channel_id=CH)
    b1, _ = snap(WORK, GUILD)
    check("отказ по причине unknown_skill", r.get("reason") == "unknown_skill", str(r))
    check("казна не тронута", b0 == b1, f"{b0} -> {b1}")

    # ── 6. Гонка: два одновременных запроса на одну прокачку ────────────────
    print("\n6. Два одновременных запроса на прокачку второго навыка (гонка)")
    SKILL2 = "cosmetic_banner_unlock"
    cost2 = GUILD_SKILLS_CONFIG[SKILL2]["cost_per_level"][0]
    c = sqlite3.connect(WORK)
    c.execute("UPDATE guilds SET balance=? WHERE id=?", (cost2, GUILD))  # ровно на ОДНУ прокачку
    c.commit()
    c.close()
    b0, _ = snap(WORK, GUILD)
    res = await asyncio.gather(
        db.upgrade_guild_skill(MASTER, SKILL2, channel_id=CH),
        db.upgrade_guild_skill(MASTER, SKILL2, channel_id=CH),
        return_exceptions=True,
    )
    b1, lvl2 = snap(WORK, GUILD, SKILL2)
    wins = sum(1 for x in res if isinstance(x, dict) and x.get("upgraded"))
    print(f"     ответы: {res}")
    check("прошла ровно одна прокачка", wins == 1, f"успешных={wins}")
    check(f"списано ровно {cost2}, а не вдвое", b0 - b1 == cost2, f"{b0} -> {b1} (разница {b0-b1})")
    check("уровень стал 1, а не 2", lvl2 == 1, f"level={lvl2}")

    # Пул надо закрыть явно, иначе процесс не завершается и код возврата не
    # приходит вовсе — прогон выглядит «зависшим». Тот же класс, что записан
    # в CLAUDE.md §4: зелёная печать без кода возврата не считается зелёной.
    # Закрывать надо ИМЕННО пул этого экземпляра Database (он создаёт свой в
    # __init__), а не глобальный через close_db_pool() — на глобальном прогон
    # всё равно висел до таймаута и код возврата не приходил.
    try:
        await db._pool.close()
    except Exception as e:
        print(f"  (пул экземпляра не закрылся: {e})")
    try:
        from db_pool import close_db_pool
        await close_db_pool()
    except Exception as e:
        print(f"  (глобальный пул не закрылся: {e})")

    print("\n" + "=" * 60)
    if fails:
        print(f"ПРОВАЛЕНО {len(fails)}: {fails}")
        return 1
    print("A6: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

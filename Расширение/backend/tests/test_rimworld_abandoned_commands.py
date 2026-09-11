"""
test_rimworld_abandoned_commands.py — платная команда RimWorld не висит вечно.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_rimworld_abandoned_commands.py

ЧТО ДОКАЗЫВАЕТ (постстрим-триаж 2026-09-11).
    На эфире 10.09 RimWorld не был запущен, а трое платных действий прошли:
    `laitru` создать пешку 200💎 и вылечить 150💎, `ethanenok` создать пешку
    200💎. Через сутки все три лежали в `rimworld_pending_commands` со
    статусом `queued`, деньги не вернулись.

    Механизм: при игре «не в эфире» `_charge_and_enqueue` кладёт команду в
    старую очередь, а её единственный сторож с возвратом берёт только
    ДОСТАВЛЕННЫЕ команды и живёт внутри опроса мода — которого нет, когда игра
    выключена. Команды попадают туда именно тогда, когда их никто не вычерпает.

    Второе, найденное по дороге: возврат из этой очереди был МОЛЧАЛИВЫМ во всех
    случаях, включая отказ мода через ack-command. 10.09 уведомление поставили
    только в новый путь (адаптер), а этот остался нем.

    Сценарий строится НАСТОЯЩИМ `_charge_and_enqueue` при выключенной игре —
    так же, как в проде, — а не вставкой строк руками: форма строки (статус,
    цена в JSON, канал) должна быть той, что пишет касса.

ТЕСТЫ:
    [0] отказ мода через ack-command: деньги назад И объяснение
    [1] просроченная недоставленная команда: деньги возвращены ровно
    [2] её строки больше нет — игра не исполнит её потом (нет двойной выгоды)
    [3] зритель получил объяснение, а не молчаливый возврат
    [4] свежая команда не тронута — игра ещё может её забрать
    [5] доставленная и не подтверждённая >10 мин тоже возвращена
    [6] доставленная недавно не тронута — игра, возможно, как раз её исполняет
    [7] повторный проход сторожа не платит дважды и не дублирует уведомления
    [8] возврат другому каналу не трогает баланс первого
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

HERE = Path(__file__).parent.absolute()
sys.path.insert(0, str(HERE.parent))

for _v, _d in (("TWITCH_OAUTH_TOKEN", "oauth:test"), ("TWITCH_CLIENT_ID", "c"),
               ("TWITCH_CLIENT_SECRET", "s"), ("TWITCH_BOT_ID", "b"),
               ("TWITCH_CHANNEL_NAME", "ch"),
               ("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab"),
               ("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890"),
               ("ADMIN_PASSWORD", "test_admin_password_for_tests_only"),
               ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(_v, _d)

CH_A = 98319857
CH_B = 5150002
START = 10000

_failures: list = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}" + (f" — {detail}" if detail else "")
        _failures.append(msg)
        print(msg)


class _FakeRequest:
    """Тело запроса мода. Приёмнику ack-command больше ничего не нужно."""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


async def _points(db, ch, user):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?", (ch, user))
        row = await cur.fetchone()
    return row[0] if row else None


async def _queue(db, ch):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT cmd_id, status FROM rimworld_pending_commands WHERE channel_id=? "
            "ORDER BY id", (ch,))
        return list(await cur.fetchall())


async def _notices(db, ch, user):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT kind, text FROM viewer_notices WHERE channel_id=? AND username=? "
            "ORDER BY id", (ch, user))
        return list(await cur.fetchall())


async def _buy(rimworld, ch, user, kind, price, extra):
    """Покупка через настоящую кассу при выключенной игре."""
    cmd = {"type": kind, "id": f"{kind}_{user}_{int(time.time())}",
           "username": user, "price": price, "channel_id": ch}
    cmd.update(extra)
    ok = await rimworld._charge_and_enqueue(user, ch, price, cmd)
    if not ok:
        raise RuntimeError(f"касса отказала: {kind} {user}")
    return cmd["id"]            # касса дописывает к id уникальный хвост


async def _age(db, cmd_id, created_ago=None, delivered_ago=None):
    """Состарить строку: как будто прошло столько-то секунд."""
    async with db._connect() as conn:
        if created_ago is not None:
            await conn.execute(
                "UPDATE rimworld_pending_commands SET created_at=datetime('now', ?) "
                "WHERE cmd_id=?", ("-%d seconds" % created_ago, cmd_id))
        if delivered_ago is not None:
            await conn.execute(
                "UPDATE rimworld_pending_commands SET status='delivered', delivered_at=? "
                "WHERE cmd_id=?", (time.time() - delivered_ago, cmd_id))
        await conn.commit()


async def _build_db(db_path: str):
    import main
    import dependencies
    from database import Database

    test_db = Database(db_path)
    main.db = test_db
    dependencies.set_db(test_db)
    await test_db.init_pool()
    await test_db.init_tables()
    await main.run_migrations()
    async with test_db._connect() as conn:
        for cid, login in ((CH_A, "alice_chan"), (CH_B, "bob_chan")):
            await conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
                "VALUES (?, ?, ?, 'free')", (cid, login, login))
        for cid, user in ((CH_A, "alice"), (CH_A, "carol"), (CH_B, "bob")):
            await conn.execute(
                "INSERT OR IGNORE INTO viewers (channel_id, username, points) "
                "VALUES (?, ?, ?)", (cid, user, START))
        await conn.commit()
    return test_db


async def run():
    db_path = tempfile.mktemp(suffix="_rw_abandoned.db")
    db = await _build_db(db_path)
    try:
        import rimworld

        print("\n[0] Отказ мода через ack-command")
        carol_cmd = await _buy(rimworld, CH_A, "carol", "heal_pawn", 150, {})
        await rimworld.ack_command(
            _FakeRequest({"command_id": carol_cmd, "success": False,
                          "message": "no_effect"}),
            mod_channel_id=CH_A)
        check("отказ мода вернул деньги", await _points(db, CH_A, "carol") == START,
              f"баланс carol {await _points(db, CH_A, 'carol')}")
        cnotes = await _notices(db, CH_A, "carol")
        check("отказ мода объяснён зрителю, а не молчаливый возврат",
              len(cnotes) == 1 and cnotes[0][0] == "refused",
              f"уведомлений: {cnotes}")

        # Игра не в эфире: module_liveness пуст — касса кладёт в старую очередь.
        old_spawn = await _buy(rimworld, CH_A, "alice", "spawn_pawn", 200, {})
        young_heal = await _buy(rimworld, CH_A, "alice", "heal_pawn", 150, {})
        stale_dlv = await _buy(rimworld, CH_A, "alice", "train_skill", 300,
                               {"skill": "Shooting"})
        fresh_dlv = await _buy(rimworld, CH_A, "alice", "train_skill", 300,
                               {"skill": "Medicine"})
        bob_spawn = await _buy(rimworld, CH_B, "bob", "spawn_pawn", 200, {})

        queued = await _queue(db, CH_A)
        check("касса положила команды в старую очередь (сценарий как на проде)",
              len(queued) == 4, f"в очереди: {queued}")
        check("деньги списаны до сторожа",
              await _points(db, CH_A, "alice") == START - 950,
              f"баланс {await _points(db, CH_A, 'alice')}")

        await _age(db, old_spawn, created_ago=2 * 3600)
        await _age(db, young_heal, created_ago=5 * 60)
        await _age(db, stale_dlv, created_ago=3 * 3600, delivered_ago=2 * 3600)
        await _age(db, fresh_dlv, created_ago=60, delivered_ago=60)
        await _age(db, bob_spawn, created_ago=2 * 3600)

        sweep = getattr(rimworld, "sweep_abandoned_commands", None)
        if sweep is None:
            check("у старой очереди есть сторож, не зависящий от опроса мода",
                  False, "команда, которую игра не забрала, висит вечно — продовый "
                         "симптом 10.09: 550💎 через сутки в status='queued'")
            return

        print("\n[1-3] Просроченная недоставленная команда")
        await sweep()
        left = {cmd_id for cmd_id, _ in await _queue(db, CH_A)}
        # вернуть должны 200 (пешка) + 300 (зависшая доставка) = 500
        check("деньги возвращены ровно за просроченное",
              await _points(db, CH_A, "alice") == START - 950 + 500,
              f"баланс {await _points(db, CH_A, 'alice')}, ждали {START - 450}")
        check("строки просроченной команды больше нет — игра её не исполнит",
              old_spawn not in left, f"в очереди осталось: {sorted(left)}")
        notes = await _notices(db, CH_A, "alice")
        check("зритель получил объяснение по каждому возврату",
              len(notes) == 2 and all(k == "refused" for k, _ in notes),
              f"уведомления: {notes}")
        check("объяснение человеческое, без сырого кода",
              bool(notes) and all("_" not in t and len(t) > 20 for _, t in notes),
              f"тексты: {[t for _, t in notes]}")

        print("\n[4] Свежая команда")
        check("свежая недоставленная не тронута", young_heal in left,
              f"в очереди: {sorted(left)}")

        print("\n[5-6] Доставленные")
        check("доставленная и молчащая 2 часа возвращена", stale_dlv not in left,
              f"в очереди: {sorted(left)}")
        check("доставленная минуту назад не тронута", fresh_dlv in left,
              f"в очереди: {sorted(left)}")

        print("\n[7] Повторный проход сторожа")
        bal = await _points(db, CH_A, "alice")
        await sweep()
        check("второй проход не платит", await _points(db, CH_A, "alice") == bal,
              f"было {bal}, стало {await _points(db, CH_A, 'alice')}")
        check("второй проход не дублирует уведомления",
              len(await _notices(db, CH_A, "alice")) == 2,
              f"уведомлений: {len(await _notices(db, CH_A, 'alice'))}")

        print("\n[8] Каналы не смешиваются")
        check("канал B получил свой возврат", await _points(db, CH_B, "bob") == START,
              f"баланс bob {await _points(db, CH_B, 'bob')}")
        check("очередь канала B вычищена", not await _queue(db, CH_B),
              f"в очереди B: {await _queue(db, CH_B)}")
    finally:
        try:
            await db._pool.close()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass


def main() -> int:
    try:
        asyncio.run(run())
    except Exception:
        traceback.print_exc()
        return 1
    print()
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print(" ", f.strip())
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())

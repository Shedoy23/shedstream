"""
test_marriage_double_accept.py — внешний аудит S-19: двойное «принять» не должно
создавать два брака.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_marriage_double_accept.py

## ⚠️ ЧЕСТНО О СИЛЕ ЭТОГО ТЕСТА

**Он ЗЕЛЁНЫЙ и на коде ДО фикса** — то есть заявленную гонку он НЕ доказывает
и доказательством фикса не является. Это характеризационный тест: он фиксирует
наблюдаемое поведение («два одновременных принять → один брак, один развод»),
а не проверку защиты. Ставить его в отчёт как «дыра закрыта» нельзя.

## Что заявлено (внешний аудит S-19) и что вышло на самом деле

Заявлено: `marriage_accept` читает предложение и проверяет «оба не в браке» БЕЗ
`BEGIN IMMEDIATE`, уникального ограничения на активного участника в схеме нет
(в `m1_multitenant` только обычный индекс) — значит двойной клик создаёт две
активные строки. Цена ошибки денежная: развод расторгает РОВНО ОДНУ строку
(`UPDATE ... WHERE id = ?`) за 500💎, так что выпутаться стоило бы двух разводов.

По коду это верно. **Воспроизвести не удалось** — включая принудительное
открытие окна (см. `_InterleavingConn`). Причина видна в трассировке вызовов:
`await conn.execute(SELECT ...)` возвращает КУРСОР, а строку достаёт отдельный
`await cursor.fetchone()` уже позже. Второй запрос успевает целиком (вставить
брак и УДАЛИТЬ предложение) до того, как первый доберётся до `fetchone()` — и
первый видит пустую выборку, отвечая «нет входящих предложений».

То есть окно закрывается **по случайности**, а не по устройству: защиту даёт
удаление предложения конкурентом, а не сериализация. `BEGIN IMMEDIATE` в фиксе
добавлен именно поэтому — чтобы инвариант держался конструкцией, а не
совпадением. Но честная формулировка: **дефект не воспроизведён, фикс —
страховка, а не доказанное лечение.**

## Что закроет вопрос

Уникальный частичный индекс на активного участника
(`UNIQUE (channel_id, user1) WHERE divorced_at IS NULL` и симметрично) — тогда
вторая строка невозможна независимо от таймингов, и это проверяется тестом,
который краснеет.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

CHANNEL_ID = 98319857
PROPOSER = "romeo"
ACCEPTER = "juliet"

_failures: list = []
_successes: list = []


def assert_eq(actual, expected, label: str):
    if actual == expected:
        _successes.append(label)
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: expected {expected!r}, got {actual!r}"
        _failures.append(msg)
        print(msg)


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
        await conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
            "VALUES (?, 'chan', 'Chan', 'free')", (CHANNEL_ID,))
        for u in (PROPOSER, ACCEPTER):
            await conn.execute(
                "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, 100000)",
                (CHANNEL_ID, u))
        await conn.execute(
            "INSERT INTO marriage_proposals (channel_id, from_user, to_user) "
            "VALUES (?, ?, ?)", (CHANNEL_ID, PROPOSER, ACCEPTER))
        await conn.commit()
    return test_db


class _FakeRequest:
    """require_jwt_user читает ContextVar/заголовки — проще подменить саму функцию."""


class _InterleavingConn:
    """Соединение, которое ГАРАНТИРОВАННО отдаёт управление перед вставкой брака.

    Без этого гонку не воспроизвести: aiosqlite выполняет запрос в своём потоке,
    и два обработчика на одном event loop успевают пройти проверку и вставку
    «встык», ни разу не переключившись в опасной точке. Тест тогда зелёный при
    ЛЮБОМ коде — то есть не измеряет ничего (ровно этим 30.07 закончилась
    попытка поймать гонку на кулдаунах).

    Поэтому окно между «проверил, что не женат» и «вставил брак» открывается
    принудительно. Это не подгонка результата: окно существует в коде, тест лишь
    делает переключение в нём неизбежным.
    """

    def __init__(self, real):
        self._real = real

    async def execute(self, sql, *a, **kw):
        if "INSERT INTO marriages" in sql:
            await asyncio.sleep(0)      # отдать управление второму запросу
        return await self._real.execute(sql, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._real, name)


async def _active_marriages(db) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM marriages WHERE channel_id=? AND divorced_at IS NULL",
            (CHANNEL_ID,))
        return (await cur.fetchone())[0]


async def _run():
    db_path = tempfile.mktemp(suffix="_marriage_test.db")
    db = await _build_db(db_path)
    try:
        import routes.marriage as m

        # Обходим JWT и гейт «стрим в эфире» — проверяем гонку, не авторизацию.
        async def _no_gate():
            return None

        m.require_stream_live = _no_gate
        m.require_jwt_user = lambda request: (ACCEPTER, CHANNEL_ID)

        class _Bot:
            async def touch_viewer(self, *a, **kw):
                return None

        import dependencies
        dependencies.get_bot = lambda: _Bot()

        # Обработчик берёт соединение через get_db()._connect(); подменяем его
        # на обёртку, открывающую окно гонки (см. _InterleavingConn).
        import contextlib
        _real_connect = db._connect

        @contextlib.asynccontextmanager
        async def _racy_connect():
            async with _real_connect() as conn:
                yield _InterleavingConn(conn)

        db._connect = _racy_connect

        print("\n[1] Два одновременных «принять» создают ОДИН брак")
        results = await asyncio.gather(
            m.marriage_accept(_FakeRequest()),
            m.marriage_accept(_FakeRequest()),
            return_exceptions=True,
        )
        ok = [r for r in results
              if isinstance(r, dict) and r.get("success")]
        refused = [r for r in results
                   if isinstance(r, dict) and not r.get("success")]
        crashed = [r for r in results if isinstance(r, BaseException)]

        assert_eq(await _active_marriages(db), 1, "активный брак ровно один")
        assert_eq(len(ok), 1, "успехом ответил ровно один запрос")
        assert_eq(len(crashed), 0,
                  f"ни один запрос не упал с исключением ({crashed})")
        assert_eq(len(refused), 1, "второй запрос получил осмысленный отказ")

        print("\n[2] Развод расторгает брак с одного раза")
        m.require_jwt_user = lambda request: (ACCEPTER, CHANNEL_ID)
        res = await m.divorce(_FakeRequest())
        assert_eq(bool(res.get("success")), True, "развод прошёл")
        assert_eq(await _active_marriages(db), 0,
                  "после ОДНОГО развода активных браков не осталось")
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


def main():
    print("=" * 70)
    print("S-19 (характеризация) — двойное «принять»: наблюдаемое поведение")
    print("=" * 70)
    try:
        asyncio.run(_run())
    except Exception:
        print("\n💥 Test harness CRASHED (не assertion — инфраструктура):")
        traceback.print_exc()
        sys.exit(2)

    print("\n" + "=" * 70)
    print(f"PASSED: {len(_successes)}   FAILED: {len(_failures)}")
    if _failures:
        print("\nFAILURES:")
        for f in _failures:
            print(f)
        sys.exit(1)
    print("ALL GREEN — поведение зафиксировано. ВНИМАНИЕ: тест зелёный и БЕЗ "
          "фикса, гонка НЕ воспроизведена — см. шапку файла.")
    sys.exit(0)


if __name__ == "__main__":
    main()
